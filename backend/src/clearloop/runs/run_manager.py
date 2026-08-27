"""Thread-safe lifecycle manager for bounded local agent runs."""

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

from clearloop.core import TraceEmitter
from clearloop.memory import MemorySummary
from clearloop.security import WorkspaceError, WorkspacePolicy, WorkspacePolicyError

from clearloop.runs.agent_runner import (
    AgentRunnerProtocol,
    RunOutcome,
    RunnerNotReadyError,
    RunSpec,
)
from clearloop.runs.approval_broker import (
    ApprovalBroker,
    ApprovalBrokerError,
    PendingApproval,
)
from clearloop.runs.event_buffer import EventBuffer, utc_now


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
    """Project the safe diagnostic vocabulary onto the public event stream."""

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
        public_name = self._EVENT_MAP.get(event)
        if public_name is not None:
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
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def summary(self) -> dict[str, Any]:
        with self.lock:
            return {
                "run_id": self.run_id,
                "status": self.status.value,
                "workspace": os.fspath(self.workspace),
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

    @property
    def stream_complete(self) -> bool:
        with self.lock:
            return self.status in TERMINAL_STATUSES and self.final_event_published

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
    """Own active-run reservations, worker threads, approvals, and retention."""

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
            thread_name_prefix="clearloop-web-run",
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

    def create(self, *, workspace: str, task: str, use_memory: bool = True) -> dict[str, Any]:
        if not isinstance(task, str) or not task.strip():
            raise RunManagerError("task_invalid", "Task must be non-empty text.", status_code=422)
        if len(task) > 100_000:
            raise RunManagerError("task_too_large", "Task is too long.", status_code=413)
        resolved_workspace = self.validate_workspace(workspace)
        key = self._workspace_key(resolved_workspace)

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
            run_id = uuid4().hex
            session = RunSession(
                run_id=run_id,
                workspace=resolved_workspace,
                buffer=EventBuffer(self.event_buffer_size),
                memory=MemorySummary(status="pending" if use_memory else "disabled"),
            )
            broker = ApprovalBroker(
                run_id=run_id,
                cancel_event=session.cancel_event,
                timeout_seconds=self.approval_timeout_seconds,
                run_deadline_seconds=self.run_deadline_seconds,
                publish=session.buffer.publish,
                pending_changed=session.set_pending,
            )
            session.approval_broker = broker
            self._sessions[run_id] = session
            self._active_workspaces[key] = run_id

        session.buffer.publish(
            "run.accepted",
            {
                "run_id": run_id,
                "status": RunStatus.STARTING.value,
                "workspace": os.fspath(resolved_workspace),
            },
        )
        try:
            future = self._executor.submit(self._execute, session, task, use_memory, key)
            session.future = future
        except RuntimeError as exc:
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
        """Atomically exclude same-workspace runs while one mutation executes."""

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
        """Confirm optional run provenance without exposing retained run content."""

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
    ) -> None:
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
            outcome = self.runner.run(
                RunSpec(session.run_id, session.workspace, task, use_memory),
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
            # Never expose provider exceptions, request data, task text, or credentials.
            session.fail("internal_run_error", "The run failed unexpectedly.")
        finally:
            # Releasing the active-workspace reservation happens-before the
            # public final event. Once clients observe run.finished, a confirmed
            # memory mutation for this workspace is guaranteed to be admissible.
            with self._lock:
                if self._active_workspaces.get(workspace_key) == session.run_id:
                    self._active_workspaces.pop(workspace_key, None)
            self._publish_finished(session)

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
                if session.terminal:
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
