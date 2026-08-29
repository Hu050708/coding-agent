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
        """初始化持久化与进程内运行协调服务。

        :param persistence: 负责运行、消息、事件和审批事务的持久化门面。
        :param manager: 负责实际 Agent 工作线程及实时事件的运行管理器。
        """

        # 两个依赖共同构成“数据库事实 + 当前进程实时状态”的双层运行视图。
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
        """以幂等方式创建持久化运行，并在本进程启动对应工作线程。

        :param conversation_id: 本次运行所属会话 ID。
        :param content: 用户当前任务正文。
        :param permission_mode: 本次运行采用的命令权限模式。
        :param use_memory: 是否装载项目记忆快照。
        :param client_request_id: 客户端生成的幂等请求 ID。
        :return: 新建或已有运行的公开投影。
        :raises ApplicationError: 供应商未配置、会话无效或工作区已有活动运行。
        """

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
        """从持久化快照还原运行上下文，并注册进程内执行回调。

        :param creation: 持久化门面返回的 ``RunCreation`` 兼容对象。
        :param content: 当前用户任务正文。
        :raises ApplicationError: 工作区丢失、运行时拒绝注册或上下文无效。
        """

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
        """返回运行投影，并在读取前修复可能遗漏的回调写入。

        :param run_id: 运行 ID。
        :return: 合并持久化事实与实时摘要后的公开运行字典。
        :raises ApplicationError: 运行不存在或持久化状态无法对账。
        """

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
            "model_calls": record.model_calls,
            "tool_calls": record.tool_calls,
            "duration_ms": record.duration_ms,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        }

    def cancel(self, run_id: str) -> dict[str, Any]:
        """同时向持久化层和进程内工作线程请求取消。

        :param run_id: 目标运行 ID。
        :return: 取消请求后的最新运行投影。
        :raises ApplicationError: 运行不存在、已结束或运行时拒绝取消。
        """

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
        """将用户审批决定交给对应进程内运行。

        :param run_id: 审批所属运行 ID。
        :param approval_id: 待处理审批 ID。
        :param decision: ``approve`` 或 ``reject``。
        :return: 决定已被运行时接受的确认字典。
        :raises ApplicationError: 运行、审批或决定状态无效。
        """

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
        """列出运行指定游标之后的公开事件视图。

        :param run_id: 运行 ID。
        :param after_seq: 断点续传游标，仅返回更大序号。
        :return: 按序号排列的事件字典列表。
        :raises ApplicationError: 运行不存在。
        """

        try:
            return [
                event_view(item)
                for item in self.persistence.list_events(run_id, after_seq=after_seq)
            ]
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc

    def event_records(self, run_id: str, *, after_seq: int = 0) -> list[RunEventRecord]:
        """读取 SSE 使用的原始不可变事件记录。

        :param run_id: 运行 ID。
        :param after_seq: 断点续传游标。
        :return: 按序号排列的持久化事件记录。
        :raises ApplicationError: 运行不存在。
        """

        try:
            return self.persistence.list_events(run_id, after_seq=after_seq)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc

    def live_buffer(self, run_id: str) -> EventBuffer | None:
        """取得仍由当前进程保留的实时事件缓冲区。

        :param run_id: 运行 ID。
        :return: 实时缓冲区；未保留或服务重启后为 None。
        """

        try:
            return self.manager.get_buffer(run_id)
        except RunManagerError:
            return None

    def is_terminal(self, run_id: str) -> bool:
        """对账后判断运行是否已经进入终态。

        :param run_id: 运行 ID。
        :return: 已完成、失败、取消、耗尽预算或中断时为 True。
        :raises ApplicationError: 运行不存在或持久化状态无法对账。
        """

        # SSE 会在每页持久化事件后轮询本方法，因此内存工作线程终止后，
        # 数据库不会永久停留在活动状态。
        self._reconcile_runtime(run_id)
        try:
            status = StoredRunStatus(self.persistence.get_run(run_id).status)
        except PersistenceNotFoundError as exc:
            raise ApplicationError(404, "run_not_found", "Run was not found.") from exc
        return status not in ACTIVE_RUN_STATUSES

    def _record_runtime_event(self, run_id: str, event: RunEvent) -> None:
        """持久化可重放事件及其状态投影，并汇总两个阶段的错误。

        :param run_id: 事件所属运行 ID。
        :param event: 进程内缓冲区刚发布的运行事件。
        :raises RuntimeError: 事件或状态投影至少一项写入失败，需要后续对账。
        """

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
        """把运行时事件投影为数据库中的运行和审批状态。

        :param run_id: 事件所属运行 ID。
        :param event: 已持久化或正在持久化的运行时事件。
        """

        # 按事件类型推进同一状态机；未知的展示事件只需保存在事件表，无需投影。
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
        """在 run.finished 后独立尝试一次幂等终态写入。

        :param run_id: 已结束运行 ID。
        :param summary: 运行管理器生成的最终公开摘要。
        :return: 终态持久化成功时为 True。
        :raises RuntimeError: 终态写入失败，需要后续对账。
        """

        try:
            self._persist_finished(run_id, summary)
            return True
        except Exception as exc:
            raise RuntimeError("terminal run state requires reconciliation") from exc

    def _reconcile_active_conversation(self, conversation_id: str) -> bool:
        """尝试修复会话工作区记录的陈旧活动运行。

        :param conversation_id: 待检查会话 ID。
        :return: 没有活动运行或活动运行已对账为终态时为 True。
        """

        try:
            conversation = self.persistence.get_conversation(conversation_id)
            active = self.persistence.active_run_for_workspace(conversation.workspace_id)
        except PersistenceNotFoundError:
            return False
        if active is None:
            return True
        return self._reconcile_runtime(str(active.id))

    def _reconcile_runtime(self, run_id: str) -> bool:
        """修复保留事件及其持久化投影，并返回运行是否已终止。

        :param run_id: 待对账运行 ID。
        :return: 对账后运行处于终态时为 True，否则为 False。
        :raises ApplicationError: 三次有界尝试后仍无法同步 PostgreSQL。
        """

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
        """把内存缓冲区中尚未持久化的事件及审批投影补写到数据库。

        :param run_id: 待修复运行 ID。
        """

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
        """把进程内运行摘要转换为持久化终态和助手消息。

        :param run_id: 已结束运行 ID。
        :param summary: 运行管理器提供的最终摘要。
        """

        # 第一步：解析终态、公开错误和以毫秒表示的运行时长。
        status = StoredRunStatus(str(summary["status"]))
        error = summary.get("error") if isinstance(summary.get("error"), dict) else {}
        duration = summary.get("duration_seconds")
        duration_ms = (
            round(float(duration) * 1000) if isinstance(duration, (int, float)) else None
        )
        # 第二步：在事务服务中原子追加助手消息并写入最终用量统计。
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
        """从 approval.required 事件创建可恢复的数据库审批记录。

        :param run_id: 审批所属运行 ID。
        :param event: 携带安全审批展示负载的运行时事件。
        :raises ValueError: 事件缺少合法审批对象或时间戳。
        """

        # 第一步：取出并解析运行时已脱敏的审批载荷。
        approval = event.data.get("approval")
        if not isinstance(approval, dict):
            raise ValueError("approval event is malformed")
        expires_at = _parse_timestamp(approval.get("expires_at"))
        # 第二步：持久化必要展示信息，使服务重启后仍能解释待审批操作。
        self.persistence.create_approval(
            approval_id=str(approval.get("approval_id", "")),
            run_id=run_id,
            tool_name=str(approval.get("tool_name") or "tool")[:64],
            action_summary=str(approval.get("action_summary") or "工具操作")[:512],
            reason=str(approval.get("reason") or "Tool approval is required."),
            expires_at=expires_at,
        )

    def _persist_approval_resolution(self, event: RunEvent) -> None:
        """将运行时审批结果映射为数据库枚举并完成审批。

        :param event: 携带审批 ID 与处理结果的运行时事件。
        """

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
        """把内部审批对象转换成不暴露工作区绝对路径的前端视图。

        :param run_id: 审批所属运行 ID。
        :param approval: 运行管理器中的内部审批摘要。
        :param workspace: 运行工作区的规范绝对路径。
        :return: 仅含审批界面所需字段和相对目录标签的字典。
        """

        # 第一步：规范化命令参数，并尽量把执行目录显示成工作区相对路径。
        argv = approval.get("argv")
        cwd = str(approval.get("cwd") or workspace)
        try:
            cwd_label = os.fspath(Path(cwd).relative_to(Path(workspace))) or "."
        except ValueError:
            cwd_label = Path(cwd).name or "."
        # 第二步：仅返回审批 UI 所需字段，并补齐稳定的展示默认值。
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
    """解析必须包含时区的 ISO 8601 时间文本。

    :param value: 待解析的外部时间值。
    :return: 带时区的 ``datetime``。
    :raises ValueError: 输入不是字符串、格式错误或缺少时区。
    """

    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


__all__ = ["ConversationRunService"]
