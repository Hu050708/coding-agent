"""协调持久化会话状态与进程内智能体运行。"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any

from coding_agent.agents import MemoryReference, VisibleMessage
from coding_agent.repository import (
    ACTIVE_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    ApprovalStatus,
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistenceService,
    RunEventRecord,
    RunStatus as StoredRunStatus,
)
from coding_agent.agents.runtime.event_buffer import EventBuffer, RunEvent
from coding_agent.agents.runtime.run_manager import RunManager, RunManagerError

from .errors import ApplicationError
from .presenters import event_view


class ConversationRunService:
    """将持久化会话与一次有边界的进程内智能体运行连接起来。"""

    def __init__(self, persistence: PersistenceService, manager: RunManager) -> None:
        self.persistence = persistence
        self.manager = manager

    def create(
        self,
        conversation_id: str,
        *,
        content: str,
        permission_mode: str,
        use_memory: bool,
        client_request_id: str,
    ) -> dict[str, Any]:
        """以幂等方式创建持久化运行，并在本进程启动对应工作线程。"""

        # 第一步：确认模型供应商可用，再在同一事务中创建运行和用户消息。
        if not self.manager.ready:
            raise ApplicationError(
                503,
                "provider_not_configured",
                "DEEPSEEK_API_KEY is not configured on the server.",
            )
        creation = None
        for attempt in range(2):
            try:
                creation = self.persistence.create_run_with_user_message(
                    conversation_id=conversation_id,
                    content=content,
                    permission_mode=permission_mode,
                    use_memory=use_memory,
                    client_request_id=client_request_id,
                    model=self.manager.model,
                )
                break
            except PersistenceNotFoundError as exc:
                raise ApplicationError(
                    404, "conversation_not_found", "Conversation was not found."
                ) from exc
            except PersistenceConflictError as exc:
                message = str(exc)
                if (
                    attempt == 0
                    and "active run" in message
                    and self._reconcile_active_conversation(conversation_id)
                ):
                    # 上一工作线程可能已结束，但终态事务曾短暂失败；先修复状态，
                    # 再在正常的工作区锁保护下重试一次新事务。
                    continue
                code = (
                    "workspace_busy"
                    if "active run" in message
                    else "conversation_unavailable"
                )
                public = (
                    "This workspace already has an active run."
                    if code == "workspace_busy"
                    else "The conversation is archived or unavailable."
                )
                raise ApplicationError(409, code, public) from exc

        if creation is None:  # 防御性检查：有界循环按设计只会成功赋值或抛出异常。
            raise ApplicationError(503, "run_start_failed", "The agent run could not be started.")

        # 第二步：重复请求只返回原运行；仅首次创建时注册进程内执行。
        if creation.created:
            self._start_runtime(creation, content=content)
        return self.get(str(creation.run.id))

    def _start_runtime(self, creation: Any, *, content: str) -> None:
        """从持久化快照还原运行上下文，并注册进程内执行回调。"""

        # 第一步：读取规范工作区、创建前的历史消息和本次运行冻结的记忆快照。
        run = creation.run
        try:
            workspace = self.persistence.get_workspace(run.workspace_id)
            history_records = getattr(creation, "prior_messages", None)
            if history_records is None:
                history_records = tuple(
                    item
                    for item in self.persistence.history(run.conversation_id)
                    if item.seq < creation.user_message.seq
                )
            history = tuple(
                VisibleMessage(role=item.role, content=item.content)
                for item in history_records
            )
            snapshots = getattr(creation, "memory_snapshot", None)
            if snapshots is None:
                snapshots = self.persistence.list_run_memories(run.id)
            memory = tuple(
                MemoryReference(
                    id=(
                        str(item.memory_entry_id)
                        if item.memory_entry_id is not None
                        else f"{run.id}:{item.position}"
                    ),
                    kind=item.kind,
                    content=item.content,
                )
                for item in snapshots
            )
            # 第二步：将事件和完成回调绑定到持久化层后再启动工作线程。
            self.manager.create(
                workspace=workspace.canonical_path,
                task=content,
                use_memory=run.use_memory,
                permission_mode=run.permission_mode,
                prior_messages=history,
                memory_snapshot=memory,
                run_id=str(run.id),
                on_event=lambda event: self._record_runtime_event(str(run.id), event),
                on_finished=lambda summary: self._record_runtime_finished(
                    str(run.id), summary
                ),
            )
        except (PersistenceNotFoundError, RunManagerError, ValueError) as exc:
            # 第三步：启动失败也必须落为终态，避免工作区被“活动运行”永久占用。
            code = getattr(exc, "code", "run_start_failed")
            try:
                self.persistence.append_assistant_message_and_finish(
                    run.id,
                    content=None,
                    status=StoredRunStatus.FAILED,
                    reason=code,
                    model_calls=0,
                    tool_calls=0,
                    usage={},
                    duration_ms=None,
                    error_code=code,
                    error_message="The agent run could not be started.",
                )
            except Exception:
                pass
            if isinstance(exc, RunManagerError):
                raise ApplicationError(exc.status_code, exc.code, exc.message) from exc
            raise ApplicationError(503, "run_start_failed", "The agent run could not be started.") from exc

    def get(self, run_id: str) -> dict[str, Any]:
        """返回运行投影，并在读取前修复可能遗漏的回调写入。"""

        # 该读取接口也是瞬时回调失败后的修复入口，因此必须先对账再读取投影。
        self._reconcile_runtime(run_id)
        try:
            record = self.persistence.get_run(run_id)
            messages = self.persistence.list_messages(record.conversation_id)
            workspace = self.persistence.get_workspace(record.workspace_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc

        # 第二步：先从持久化助手消息构建最终内容，再用仍在运行的内存摘要补充实时字段。
        final_content = next(
            (
                item.content
                for item in reversed(messages)
                if str(item.run_id) == str(record.id) and item.role == "assistant"
            ),
            None,
        )
        pending: dict[str, Any] | None = None
        active_summary: dict[str, Any] | None = None
        try:
            active_summary = self.manager.get(str(record.id))
        except RunManagerError:
            pass
        if active_summary is not None:
            final_content = active_summary.get("final_content") or final_content
            raw_pending = active_summary.get("pending_approval")
            if isinstance(raw_pending, dict):
                pending = self._pending_approval_view(
                    str(record.id), raw_pending, workspace.canonical_path
                )

        # 第三步：仅返回稳定的公开错误字段和用量投影，不暴露内部异常。
        error = None
        if record.error_code:
            error = {
                "code": record.error_code,
                "message": record.error_message or "The run failed.",
            }
        return {
            "id": record.id,
            "conversation_id": record.conversation_id,
            "workspace_id": record.workspace_id,
            "status": record.status,
            "permission_mode": record.permission_mode,
            "use_memory": record.use_memory,
            "model": record.model or self.manager.model,
            "final_content": final_content,
            "reason": record.reason,
            "error": error,
            "pending_approval": pending,
            "usage": {
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "total_tokens": record.total_tokens,
                "prompt_cache_hit_tokens": record.prompt_cache_hit_tokens,
                "prompt_cache_miss_tokens": record.prompt_cache_miss_tokens,
            },
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        }

    def cancel(self, run_id: str) -> dict[str, Any]:
        try:
            self.persistence.request_cancel(run_id)
            self.manager.cancel(run_id)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc
        except PersistenceConflictError as exc:
            raise ApplicationError(409, "run_not_active", "Run is no longer active.") from exc
        except RunManagerError as exc:
            raise ApplicationError(exc.status_code, exc.code, exc.message) from exc
        return self.get(run_id)

    def resolve_approval(
        self, run_id: str, approval_id: str, decision: str
    ) -> dict[str, Any]:
        try:
            self.manager.resolve_approval(run_id, approval_id, decision)
        except RunManagerError as exc:
            raise ApplicationError(exc.status_code, exc.code, exc.message) from exc
        return {
            "run_id": run_id,
            "approval_id": approval_id,
            "decision": decision,
            "accepted": True,
        }

    def list_events(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        try:
            return [
                event_view(item)
                for item in self.persistence.list_events(run_id, after_seq=after_seq)
            ]
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc

    def event_records(self, run_id: str, *, after_seq: int = 0) -> list[RunEventRecord]:
        try:
            return self.persistence.list_events(run_id, after_seq=after_seq)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc

    def live_buffer(self, run_id: str) -> EventBuffer | None:
        try:
            return self.manager.get_buffer(run_id)
        except RunManagerError:
            return None

    def is_terminal(self, run_id: str) -> bool:
        # SSE 会在每页持久化事件后轮询本方法，因此内存工作线程终止后，
        # 数据库不会永久停留在活动状态。
        self._reconcile_runtime(run_id)
        try:
            status = StoredRunStatus(self.persistence.get_run(run_id).status)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc
        return status not in ACTIVE_RUN_STATUSES

    def _record_runtime_event(self, run_id: str, event: RunEvent) -> None:
        """持久化可重放事件及其状态投影，并汇总两个阶段的错误。"""

        # 先写可重放事件，再更新投影。EventBuffer 会在回调返回后才通知 SSE，
        # 因而被唤醒的客户端能同时看到事件及其对应状态。
        errors: list[Exception] = []
        try:
            self.persistence.append_safe_event(
                run_id,
                seq=event.seq,
                event=event.event,
                timestamp=event.timestamp,
                data=event.data,
            )
        except Exception as exc:
            errors.append(exc)
        try:
            self._project_runtime_event(run_id, event)
        except Exception as exc:
            errors.append(exc)
        if errors:
            # EventBuffer 会在集成边界捕获此错误，智能体循环仍可继续；随后由
            # GET、SSE 或新运行入口显式重放并修复保留会话，避免静默丢失状态。
            raise RuntimeError("durable run callback requires reconciliation") from errors[0]

    def _project_runtime_event(self, run_id: str, event: RunEvent) -> None:
        if event.event == "run.started":
            self.persistence.set_run_status(
                run_id, StoredRunStatus.RUNNING, started_at=event.timestamp
            )
        elif event.event == "approval.required":
            self._persist_approval_required(run_id, event)
            self.persistence.set_run_status(run_id, StoredRunStatus.WAITING_APPROVAL)
        elif event.event == "approval.resolved":
            self._persist_approval_resolution(event)
            current = self.persistence.get_run(run_id)
            if current.status != StoredRunStatus.CANCELLING.value:
                self.persistence.set_run_status(run_id, StoredRunStatus.RUNNING)
        elif event.event == "run.finished":
            summary = self.manager.get(run_id)
            self._persist_finished(run_id, summary)

    def _record_runtime_finished(self, run_id: str, summary: dict[str, Any]) -> bool:
        """在 run.finished 后独立尝试一次幂等终态写入。"""

        try:
            self._persist_finished(run_id, summary)
            return True
        except Exception as exc:
            raise RuntimeError("terminal run state requires reconciliation") from exc

    def _reconcile_active_conversation(self, conversation_id: str) -> bool:
        try:
            conversation = self.persistence.get_conversation(conversation_id)
            active = self.persistence.active_run_for_workspace(conversation.workspace_id)
        except PersistenceNotFoundError:
            return False
        if active is None:
            return True
        return self._reconcile_runtime(str(active.id))

    def _reconcile_runtime(self, run_id: str) -> bool:
        """修复保留事件及其持久化投影，并返回运行是否已终止。"""

        # 第一步：在有限次数内比较数据库投影、内存摘要和回调错误计数。
        buffer = self.live_buffer(run_id)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                durable = self.persistence.get_run(run_id)
                durable_status = StoredRunStatus(durable.status)
                needs_event_repair = buffer is not None and buffer.callback_errors > 0

                if durable_status in TERMINAL_RUN_STATUSES:
                    if needs_event_repair:
                        self._replay_retained_events(run_id)
                    if buffer is not None:
                        self.manager.mark_durable_finalized(run_id)
                        buffer.acknowledge_callback_errors()
                    return True

                summary = self.manager.get(run_id)
                if needs_event_repair:
                    self._replay_retained_events(run_id)

                # 第二步：重放后重新读取；同步期间工作线程可能已自行提交终态事务。
                durable = self.persistence.get_run(run_id)
                durable_status = StoredRunStatus(durable.status)
                if durable_status in TERMINAL_RUN_STATUSES:
                    if buffer is not None:
                        self.manager.mark_durable_finalized(run_id)
                        buffer.acknowledge_callback_errors()
                    return True

                # 第三步：以内存终态补全数据库，非终态则只同步状态和启动时间。
                status = StoredRunStatus(str(summary["status"]))
                if status in TERMINAL_RUN_STATUSES:
                    self._persist_finished(run_id, summary)
                    if buffer is not None:
                        self.manager.mark_durable_finalized(run_id)
                        buffer.acknowledge_callback_errors()
                    return True

                started_at = summary.get("started_at")
                fields: dict[str, Any] = {}
                if isinstance(started_at, str):
                    fields["started_at"] = _parse_timestamp(started_at)
                if (
                    durable_status is not status
                    or (durable.started_at is None and "started_at" in fields)
                ):
                    self.persistence.set_run_status(run_id, status, **fields)
                if buffer is not None:
                    buffer.acknowledge_callback_errors()
                return False
            except RunManagerError:
                return False
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    # 读取可能与工作线程的最终事务重叠；短暂且有界的重试既能消除
                    # 该竞态，也能覆盖瞬时数据库断连，但不会无限掩盖故障。
                    time.sleep(0.01 * (2**attempt))

        raise ApplicationError(
            503,
            "run_persistence_unavailable",
            "The run state could not be synchronized with PostgreSQL.",
        ) from last_error

    def _replay_retained_events(self, run_id: str) -> None:
        """把内存缓冲区中尚未持久化的事件及审批投影补写到数据库。"""

        buffer = self.live_buffer(run_id)
        if buffer is None:
            return

        # 第一步：分页收集已持久化序号，用序号保证补写操作幂等。
        persisted_sequences: set[int] = set()
        after_seq = 0
        while True:
            page = self.persistence.list_events(run_id, after_seq=after_seq, limit=5_000)
            persisted_sequences.update(item.seq for item in page)
            if len(page) < 5_000:
                break
            after_seq = page[-1].seq

        # 第二步：仅补写数据库中缺失的缓冲事件。
        events, _gap = buffer.read_after(0)
        for event in events:
            if event.seq not in persisted_sequences:
                self.persistence.append_safe_event(
                    run_id,
                    seq=event.seq,
                    event=event.event,
                    timestamp=event.timestamp,
                    data=event.data,
                )

        # 第三步：审批写入是幂等的，因此可根据保留事件补全只提交了一半的投影。
        for event in events:
            if event.event == "approval.required":
                self._persist_approval_required(run_id, event)
            elif event.event == "approval.resolved":
                try:
                    self._persist_approval_resolution(event)
                except PersistenceNotFoundError:
                    # 若更早的“需要审批”事件已被有界缓冲区淘汰，就无法安全还原
                    # argv/cwd；此时仍允许终态对账继续完成。
                    continue

    def _persist_finished(self, run_id: str, summary: dict[str, Any]) -> None:
        status = StoredRunStatus(str(summary["status"]))
        error = summary.get("error") if isinstance(summary.get("error"), dict) else {}
        duration = summary.get("duration_seconds")
        duration_ms = (
            round(float(duration) * 1000) if isinstance(duration, (int, float)) else None
        )
        self.persistence.append_assistant_message_and_finish(
            run_id,
            content=summary.get("final_content"),
            status=status,
            reason=summary.get("reason"),
            model_calls=int(summary.get("model_calls", 0)),
            tool_calls=int(summary.get("tool_calls", 0)),
            usage=summary.get("usage") if isinstance(summary.get("usage"), dict) else {},
            duration_ms=duration_ms,
            error_code=error.get("code"),
            error_message=error.get("message"),
        )

    def _persist_approval_required(self, run_id: str, event: RunEvent) -> None:
        approval = event.data.get("approval")
        if not isinstance(approval, dict):
            raise ValueError("approval event is malformed")
        expires_at = _parse_timestamp(approval.get("expires_at"))
        self.persistence.create_approval(
            approval_id=str(approval.get("approval_id", "")),
            run_id=run_id,
            tool_name=str(approval.get("tool_name") or "tool")[:64],
            action_summary=str(approval.get("action_summary") or "工具操作")[:512],
            reason=str(approval.get("reason") or "Tool approval is required."),
            expires_at=expires_at,
        )

    def _persist_approval_resolution(self, event: RunEvent) -> None:
        resolution = str(event.data.get("resolution") or "reject")
        status = {
            "approve": ApprovalStatus.APPROVED,
            "reject": ApprovalStatus.REJECTED,
            "expired": ApprovalStatus.EXPIRED,
            "cancelled": ApprovalStatus.CANCELLED,
        }.get(resolution, ApprovalStatus.REJECTED)
        self.persistence.resolve_approval(
            str(event.data.get("approval_id", "")), status=status
        )

    @staticmethod
    def _pending_approval_view(
        run_id: str, approval: dict[str, Any], workspace: str
    ) -> dict[str, Any]:
        argv = approval.get("argv")
        cwd = str(approval.get("cwd") or workspace)
        try:
            cwd_label = os.fspath(Path(cwd).relative_to(Path(workspace))) or "."
        except ValueError:
            cwd_label = Path(cwd).name or "."
        return {
            "id": approval.get("approval_id"),
            "run_id": run_id,
            "tool_name": approval.get("tool_name") or "tool",
            "action_summary": approval.get("action_summary") or "工具操作",
            "argv": argv if isinstance(argv, list) else [],
            "cwd_label": cwd_label,
            "reason": approval.get("reason") or "Tool approval is required.",
            "status": "pending",
            "created_at": approval.get("created_at"),
            "expires_at": approval.get("expires_at"),
        }


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


__all__ = ["ConversationRunService"]
