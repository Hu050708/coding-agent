"""管理有边界本地智能体运行生命周期的线程安全组件。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import os
from pathlib import Path
import threading
from typing import Any, Iterator
from uuid import uuid4

from coding_agent.agents import MemoryReference, TraceEmitter, VisibleMessage
from coding_agent.agents.memory import MemorySummary
from coding_agent.agents.security import (
    PermissionMode,
    WorkspaceError,
    WorkspacePolicy,
    WorkspacePolicyError,
)

from coding_agent.agents.runtime.agent_runner import (
    AgentRunnerProtocol,
    RunOutcome,
    RunnerNotReadyError,
    RunSpec,
)
from coding_agent.agents.runtime.approval_broker import (
    ApprovalBroker,
    ApprovalBrokerError,
    PendingApproval,
)
from coding_agent.agents.runtime.event_buffer import EventBuffer, RunEvent, utc_now


class RunStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BUDGET_EXHAUSTED,
    }
)


class RunManagerError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _empty_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
    }


class BufferTrace(TraceEmitter):
    """将安全诊断字段投影到公共事件流。"""

    _EVENT_MAP = {
        "memory_loaded": "memory.loaded",
        "model_completed": "model.completed",
        "tool_started": "tool.started",
        "tool_completed": "tool.completed",
    }

    def __init__(
        self,
        buffer: EventBuffer,
        *,
        memory_changed: Callable[[MemorySummary], None] | None = None,
    ) -> None:
        self.buffer = buffer
        self.memory_changed = memory_changed

    def emit(self, event: str, /, **fields: Any) -> None:
        """把内部诊断事件映射为公开事件，并专门规范化记忆摘要。"""

        # 第一步：只接受映射表中的安全事件名，未知事件直接忽略。
        public_name = self._EVENT_MAP.get(event)
        if public_name is not None:
            # 第二步：记忆事件逐字段校验并同步会话摘要，其他事件复制安全字段。
            if event == "memory_loaded":
                raw_status = fields.get("status", "unavailable")
                status = (
                    raw_status
                    if raw_status in {"loaded", "empty", "disabled", "unavailable"}
                    else "unavailable"
                )
                raw_ids = fields.get("loaded_ids", [])
                loaded_ids = (
                    tuple(item for item in raw_ids if isinstance(item, str))
                    if isinstance(raw_ids, (list, tuple))
                    else ()
                )
                raw_count = fields.get("loaded_count", 0)
                loaded_count = (
                    raw_count
                    if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0
                    else len(loaded_ids)
                )
                summary = MemorySummary(
                    status=status,
                    loaded_count=loaded_count,
                    loaded_ids=loaded_ids,
                )
                payload = {
                    "status": summary.status,
                    "loaded_count": summary.loaded_count,
                    "loaded_ids": list(summary.loaded_ids),
                }
                if self.memory_changed is not None:
                    try:
                        self.memory_changed(summary)
                    except Exception:
                        pass
            else:
                payload = dict(fields)
            if "tool" in payload:
                payload["tool_name"] = payload.pop("tool")
            self.buffer.publish(public_name, payload)


@dataclass(slots=True)
class RunSession:
    run_id: str
    workspace: Path
    buffer: EventBuffer
    permission_mode: PermissionMode = PermissionMode.AGENT
    on_finished: Callable[[dict[str, Any]], bool | None] | None = field(
        default=None, repr=False
    )
    cancel_event: threading.Event = field(default_factory=threading.Event)
    status: RunStatus = RunStatus.STARTING
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    final_content: str | None = None
    reason: str | None = None
    error: dict[str, str] | None = None
    model_calls: int = 0
    tool_calls: int = 0
    usage: dict[str, int] = field(default_factory=_empty_usage)
    duration_seconds: float | None = None
    memory: MemorySummary = field(default_factory=lambda: MemorySummary(status="pending"))
    pending_approval: PendingApproval | None = None
    approval_broker: ApprovalBroker | None = None
    future: Future[None] | None = None
    final_event_published: bool = False
    durable_finalized: bool = True
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "run_id": self.run_id,
                "status": self.status.value,
                "workspace": os.fspath(self.workspace),
                "permission_mode": self.permission_mode.value,
                "created_at": _utc_text(self.created_at),
                "started_at": _utc_text(self.started_at),
                "finished_at": _utc_text(self.finished_at),
                "final_content": self.final_content,
                "reason": self.reason,
                "error": dict(self.error) if self.error is not None else None,
                "model_calls": self.model_calls,
                "tool_calls": self.tool_calls,
                "usage": dict(self.usage),
                "duration_seconds": self.duration_seconds,
                "memory": self.memory.as_dict(),
                "pending_approval": (
                    self.pending_approval.as_dict() if self.pending_approval is not None else None
                ),
                "cancel_requested": self.cancel_event.is_set(),
            }

    @property
    def terminal(self) -> bool:
        with self.lock:
            return self.status in TERMINAL_STATUSES

    def mark_running(self) -> bool:
        with self.lock:
            if self.cancel_event.is_set():
                return False
            self.status = RunStatus.RUNNING
            self.started_at = utc_now()
            return True

    def set_pending(self, pending: PendingApproval | None) -> None:
        with self.lock:
            self.pending_approval = pending
            if self.status in TERMINAL_STATUSES or self.status is RunStatus.CANCELLING:
                return
            self.status = RunStatus.WAITING_APPROVAL if pending is not None else RunStatus.RUNNING

    def set_memory(self, memory: MemorySummary) -> None:
        with self.lock:
            if self.memory.status != "disabled":
                self.memory = memory

    def mark_final_event_published(self) -> None:
        with self.lock:
            self.final_event_published = True

    def mark_durable_finalized(self) -> None:
        with self.lock:
            self.durable_finalized = True

    @property
    def stream_complete(self) -> bool:
        with self.lock:
            return self.status in TERMINAL_STATUSES and self.final_event_published

    @property
    def evictable(self) -> bool:
        with self.lock:
            return (
                self.status in TERMINAL_STATUSES
                and self.final_event_published
                and self.durable_finalized
            )

    def request_cancel(self) -> bool:
        with self.lock:
            if self.status in TERMINAL_STATUSES:
                return False
            self.cancel_event.set()
            self.status = RunStatus.CANCELLING
            broker = self.approval_broker
        if broker is not None:
            broker.cancel()
        return True

    def finish(self, outcome: RunOutcome) -> None:
        with self.lock:
            cancelled = self.cancel_event.is_set() or outcome.status == "cancelled"
            if cancelled:
                self.status = RunStatus.CANCELLED
                self.reason = "user_cancelled"
                self.final_content = None
            elif outcome.status == "model_finished":
                self.status = RunStatus.COMPLETED
                self.reason = outcome.reason
                self.final_content = outcome.final_content
            elif outcome.status == "budget_exhausted":
                self.status = RunStatus.BUDGET_EXHAUSTED
                self.reason = outcome.reason
                self.final_content = outcome.final_content
            else:
                self.status = RunStatus.FAILED
                self.reason = outcome.reason
                self.final_content = outcome.final_content
            self.model_calls = outcome.model_calls
            self.tool_calls = outcome.tool_calls
            self.usage = dict(outcome.usage)
            self.duration_seconds = outcome.duration_seconds
            if self.memory.status != "disabled":
                self.memory = outcome.memory
            self.pending_approval = None
            self.finished_at = utc_now()

    def fail(self, code: str, message: str) -> None:
        with self.lock:
            if self.cancel_event.is_set():
                self.status = RunStatus.CANCELLED
                self.reason = "user_cancelled"
                self.error = None
            else:
                self.status = RunStatus.FAILED
                self.reason = code
                self.error = {"code": code, "message": message}
            if self.memory.status == "pending":
                self.memory = MemorySummary(status="unavailable")
            self.pending_approval = None
            self.finished_at = utc_now()


class RunManager:
    """统一管理活动运行占位、工作线程、审批和终态会话保留。"""

    def __init__(
        self,
        *,
        runner: AgentRunnerProtocol,
        workspace_policy: WorkspacePolicy,
        max_active_runs: int = 1,
        max_retained_runs: int = 50,
        event_buffer_size: int = 256,
        approval_timeout_seconds: float = 480.0,
        run_deadline_seconds: float | None = None,
    ) -> None:
        self.runner = runner
        self.workspace_policy = workspace_policy
        self.max_active_runs = max_active_runs
        self.max_retained_runs = max_retained_runs
        self.event_buffer_size = event_buffer_size
        self.approval_timeout_seconds = approval_timeout_seconds
        self.run_deadline_seconds = run_deadline_seconds
        self._sessions: OrderedDict[str, RunSession] = OrderedDict()
        self._active_workspaces: dict[str, str] = {}
        self._memory_mutations: set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=max_active_runs,
            thread_name_prefix="coding-agent-web-run",
        )
        self._lock = threading.RLock()
        self._closing = False

    @property
    def ready(self) -> bool:
        return bool(self.runner.ready)

    @property
    def model(self) -> str:
        return self.runner.model

    @property
    def active_runs(self) -> int:
        with self._lock:
            return len(self._active_workspaces)

    def validate_workspace(self, value: str) -> Path:
        try:
            return self.workspace_policy.validate(value)
        except WorkspacePolicyError as exc:
            raise RunManagerError(exc.code, exc.message, status_code=400) from exc

    def create(
        self,
        *,
        workspace: str,
        task: str,
        use_memory: bool = True,
        permission_mode: PermissionMode | str = PermissionMode.AGENT,
        prior_messages: tuple[VisibleMessage, ...] = (),
        memory_snapshot: tuple[MemoryReference, ...] | None = None,
        run_id: str | None = None,
        on_event: Callable[[RunEvent], None] | None = None,
        on_finished: Callable[[dict[str, Any]], bool | None] | None = None,
    ) -> dict[str, Any]:
        """校验请求、原子预留工作区，并把运行提交到后台线程池。"""

        # 第一步：在获取全局锁前完成纯输入校验和工作区规范化。
        if not isinstance(task, str) or not task.strip():
            raise RunManagerError("task_invalid", "Task must be non-empty text.", status_code=422)
        if len(task) > 100_000:
            raise RunManagerError("task_too_large", "Task is too long.", status_code=413)
        try:
            resolved_permission = PermissionMode.parse(permission_mode)
        except ValueError as exc:
            raise RunManagerError(
                "permission_mode_invalid",
                "Permission mode must be ask, agent, or workspace_full.",
                status_code=422,
            ) from exc
        if not isinstance(prior_messages, tuple) or not all(
            isinstance(message, VisibleMessage) for message in prior_messages
        ):
            raise RunManagerError(
                "conversation_history_invalid",
                "Conversation history is malformed.",
                status_code=422,
            )
        if memory_snapshot is not None and (
            not isinstance(memory_snapshot, tuple)
            or not all(isinstance(item, MemoryReference) for item in memory_snapshot)
        ):
            raise RunManagerError(
                "memory_snapshot_invalid",
                "Workspace memory snapshot is malformed.",
                status_code=422,
            )
        if run_id is None:
            resolved_run_id = uuid4().hex
        elif not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128:
            raise RunManagerError("run_id_invalid", "Run ID is invalid.", status_code=422)
        else:
            resolved_run_id = run_id.strip()
        resolved_workspace = self.validate_workspace(workspace)
        key = self._workspace_key(resolved_workspace)

        # 第二步：在同一临界区检查容量、工作区冲突和会话保留条件。
        with self._lock:
            if self._closing:
                raise RunManagerError(
                    "service_shutting_down", "The service is shutting down.", status_code=503
                )
            if key in self._memory_mutations:
                raise RunManagerError(
                    "memory_mutation_in_progress",
                    "Project memory is being changed for this workspace.",
                    status_code=409,
                )
            if not self.ready:
                raise RunManagerError(
                    "provider_not_configured",
                    "DEEPSEEK_API_KEY is not configured on the server.",
                    status_code=503,
                )
            if key in self._active_workspaces:
                raise RunManagerError(
                    "workspace_busy", "This workspace already has an active run.", status_code=409
                )
            if len(self._active_workspaces) >= self.max_active_runs:
                raise RunManagerError(
                    "run_capacity_reached", "The active-run limit has been reached.", status_code=429
                )
            self._evict_terminal_locked()
            if len(self._sessions) >= self.max_retained_runs:
                raise RunManagerError(
                    "run_retention_unavailable",
                    "Completed runs are awaiting durable finalization.",
                    status_code=503,
                )
            if resolved_run_id in self._sessions:
                raise RunManagerError(
                    "run_already_registered",
                    "This run is already registered in the active process.",
                    status_code=409,
                )
            # 第三步：先完整装配会话、事件缓冲区和审批代理，再登记活动占位。
            session = RunSession(
                run_id=resolved_run_id,
                workspace=resolved_workspace,
                buffer=EventBuffer(self.event_buffer_size, on_publish=on_event),
                permission_mode=resolved_permission,
                on_finished=on_finished,
                durable_finalized=on_finished is None,
                memory=MemorySummary(status="pending" if use_memory else "disabled"),
            )
            broker = ApprovalBroker(
                run_id=resolved_run_id,
                cancel_event=session.cancel_event,
                timeout_seconds=self.approval_timeout_seconds,
                run_deadline_seconds=self.run_deadline_seconds,
                publish=session.buffer.publish,
                pending_changed=session.set_pending,
            )
            session.approval_broker = broker
            self._sessions[resolved_run_id] = session
            self._active_workspaces[key] = resolved_run_id

        # 第四步：登记成功后发布 accepted 事件，再把实际执行提交到线程池。
        session.buffer.publish(
            "run.accepted",
            {
                "run_id": resolved_run_id,
                "status": RunStatus.STARTING.value,
            },
        )
        try:
            future = self._executor.submit(
                self._execute,
                session,
                task,
                use_memory,
                key,
                prior_messages,
                memory_snapshot,
            )
            session.future = future
        except RuntimeError as exc:
            # 提交失败时撤销工作区占位，并把已登记会话转为可观察的失败终态。
            with self._lock:
                self._active_workspaces.pop(key, None)
            session.fail("run_start_failed", "The run worker could not be started.")
            raise RunManagerError(
                "run_start_failed", "The run worker could not be started.", status_code=503
            ) from exc
        return session.summary()

    def get(self, run_id: str) -> dict[str, Any]:
        return self._session(run_id).summary()

    def get_buffer(self, run_id: str) -> EventBuffer:
        return self._session(run_id).buffer

    def is_terminal(self, run_id: str) -> bool:
        return self._session(run_id).terminal

    def is_stream_complete(self, run_id: str) -> bool:
        return self._session(run_id).stream_complete

    def cancel(self, run_id: str) -> dict[str, Any]:
        session = self._session(run_id)
        session.request_cancel()
        return session.summary()

    def resolve_approval(self, run_id: str, approval_id: str, decision: str) -> None:
        session = self._session(run_id)
        broker = session.approval_broker
        if broker is None:
            raise RunManagerError(
                "approval_not_pending", "There is no pending approval.", status_code=409
            )
        try:
            broker.resolve(approval_id, decision)
        except ApprovalBrokerError as exc:
            raise RunManagerError(exc.code, exc.message, status_code=409) from exc

    @contextmanager
    def reserve_memory_mutation(self, workspace: str) -> Iterator[Path]:
        """执行一次变更期间，原子排除同工作区运行。"""

        resolved_workspace = self.validate_workspace(workspace)
        key = self._workspace_key(resolved_workspace)
        with self._lock:
            if self._closing:
                raise RunManagerError(
                    "service_shutting_down", "The service is shutting down.", status_code=503
                )
            if key in self._active_workspaces:
                raise RunManagerError(
                    "memory_workspace_busy",
                    "Project memory cannot be changed while this workspace has an active run.",
                    status_code=409,
                )
            if key in self._memory_mutations:
                raise RunManagerError(
                    "memory_mutation_in_progress",
                    "Project memory is already being changed for this workspace.",
                    status_code=409,
                )
            self._memory_mutations.add(key)
        try:
            yield resolved_workspace
        finally:
            with self._lock:
                self._memory_mutations.discard(key)

    def validate_memory_source(self, run_id: str, workspace: str) -> None:
        """确认可选运行来源，且不暴露保留的运行内容。"""

        resolved_workspace = self.validate_workspace(workspace)
        try:
            session = self._session(run_id)
        except RunManagerError as exc:
            raise RunManagerError(
                "memory_not_found", "The source run was not found.", status_code=404
            ) from exc
        expected = self._workspace_key(resolved_workspace)
        with session.lock:
            actual = self._workspace_key(session.workspace)
            source_status = session.status
        if actual != expected:
            raise RunManagerError(
                "memory_workspace_mismatch",
                "The source run belongs to a different workspace.",
                status_code=409,
            )
        if source_status is not RunStatus.COMPLETED:
            raise RunManagerError(
                "memory_source_run_ineligible",
                "Only a completed source run can be saved as project memory.",
                status_code=409,
            )

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._lock:
            sessions = tuple(self._sessions.values())[-safe_limit:]
        return [session.summary() for session in reversed(sessions)]

    def shutdown(self, *, wait: bool = False) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            active_ids = tuple(self._active_workspaces.values())
        for run_id in active_ids:
            try:
                self._session(run_id).request_cancel()
            except RunManagerError:
                continue
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _execute(
        self,
        session: RunSession,
        task: str,
        use_memory: bool,
        workspace_key: str,
        prior_messages: tuple[VisibleMessage, ...],
        memory_snapshot: tuple[MemoryReference, ...] | None,
    ) -> None:
        """在线程池中执行一个会话，并保证任何退出路径都完成资源收尾。"""

        # 第一步：把会话切换为运行态，并发布可供持久化层投影的启动事件。
        try:
            if not session.mark_running():
                session.fail("user_cancelled", "")
                return
            session.buffer.publish(
                "run.started",
                {"run_id": session.run_id, "status": RunStatus.RUNNING.value},
            )
            broker = session.approval_broker
            assert broker is not None
            # 第二步：将取消、审批和跟踪适配器注入同步智能体执行器。
            outcome = self.runner.run(
                RunSpec(
                    run_id=session.run_id,
                    workspace=session.workspace,
                    task=task,
                    use_memory=use_memory,
                    permission_mode=session.permission_mode,
                    prior_messages=prior_messages,
                    memory_snapshot=memory_snapshot,
                ),
                cancel_event=session.cancel_event,
                confirm_command=broker.confirm,
                trace=BufferTrace(session.buffer, memory_changed=session.set_memory),
            )
            session.finish(outcome)
        except RunnerNotReadyError:
            session.fail("provider_not_configured", "The model provider is not configured.")
        except WorkspaceError as exc:
            session.fail(exc.code, exc.message)
        except ValueError:
            session.fail("run_configuration_error", "The run configuration is invalid.")
        except Exception:
            # 不向客户端暴露供应商异常、请求内容、任务文本或凭据。
            session.fail("internal_run_error", "The run failed unexpectedly.")
        finally:
            # 第三步：先释放工作区占位，再发布最终事件。客户端一旦看到 run.finished，
            # 就能确定该工作区已允许执行经过确认的记忆变更。
            with self._lock:
                if self._active_workspaces.get(workspace_key) == session.run_id:
                    self._active_workspaces.pop(workspace_key, None)
            self._publish_finished(session)
            if session.on_finished is not None:
                try:
                    if session.on_finished(session.summary()) is True:
                        session.mark_durable_finalized()
                except Exception:
                    # API 仍可重试持久化终态，外层存储故障不能卡住工作线程。
                    pass

    def mark_durable_finalized(self, run_id: str) -> None:
        """允许已对账的终态会话参与保留淘汰。"""

        self._session(run_id).mark_durable_finalized()

    def _publish_finished(self, session: RunSession) -> None:
        summary = session.summary()
        session.buffer.publish(
            "run.finished",
            {
                "run_id": session.run_id,
                "status": summary["status"],
                "reason": summary["reason"],
                "model_calls": summary["model_calls"],
                "tool_calls": summary["tool_calls"],
                "usage": summary["usage"],
                "duration_seconds": summary["duration_seconds"],
            },
        )
        session.mark_final_event_published()

    def _session(self, run_id: str) -> RunSession:
        if not isinstance(run_id, str) or not run_id:
            raise RunManagerError("run_not_found", "Run was not found.", status_code=404)
        with self._lock:
            session = self._sessions.get(run_id)
        if session is None:
            raise RunManagerError("run_not_found", "Run was not found.", status_code=404)
        return session

    @staticmethod
    def _workspace_key(workspace: Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(workspace)))

    def _evict_terminal_locked(self) -> None:
        while len(self._sessions) >= self.max_retained_runs:
            evicted = False
            for run_id, session in tuple(self._sessions.items()):
                if session.evictable:
                    self._sessions.pop(run_id, None)
                    evicted = True
                    break
            if not evicted:
                break


__all__ = [
    "BufferTrace",
    "RunManager",
    "RunManagerError",
    "RunSession",
    "RunStatus",
    "TERMINAL_STATUSES",
]
