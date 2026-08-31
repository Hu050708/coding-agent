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
    """进程内 Agent 运行的生命周期状态。"""

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
    """运行生命周期操作无法按当前状态完成时抛出。"""

    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        """创建带稳定 HTTP 映射信息的运行管理错误。

        :param code: 机器可读错误码。
        :param message: 可安全返回客户端的错误说明。
        :param status_code: API 层应返回的 HTTP 状态码。
        """

        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

def _utc_text(value: datetime | None) -> str | None:
    """把可选 UTC 时间转换为以 ``Z`` 结尾的 ISO-8601 文本。

    :param value: 带时区时间或 ``None``。
    :return: 规范时间文本；空值保持为 ``None``。
    """

    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")

def _empty_usage() -> dict[str, int]:
    """创建所有已知 token 计数均为零的新字典。

    :return: 可由单个运行会话独占修改的用量字典。
    """

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
        """创建把内部诊断投影到公开事件缓冲区的接收器。

        :param buffer: 接收公开运行事件的线程安全缓冲区。
        :param memory_changed: 记忆加载摘要变化时同步更新会话的可选回调。
        """

        self.buffer = buffer
        self.memory_changed = memory_changed

    def emit(self, event: str, /, **fields: Any) -> None:
        """把内部诊断事件映射为公开事件，并专门规范化记忆摘要。

        :param event: 内部诊断事件名称。
        :param fields: 已通过核心白名单的事件字段。
        """

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
    """一个进程内运行的可变线程安全生命周期状态。"""

    # 与持久化记录和客户端 URL 一致的运行标识。
    run_id: str
    # 已通过白名单策略校验的规范工作区路径。
    workspace: Path
    # 当前运行专属的公开事件缓冲区。
    buffer: EventBuffer
    # 运行创建时冻结的权限模式。
    permission_mode: PermissionMode = PermissionMode.AGENT
    # 运行终止后由外层持久化并返回是否完成对账的回调。
    on_finished: Callable[[dict[str, Any]], bool | None] | None = field(
        default=None, repr=False
    )
    # 协作式取消信号，供 Agent、命令和审批等待共同查询。
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # 当前运行生命周期状态。
    status: RunStatus = RunStatus.STARTING
    # 会话进入管理器的 UTC 时间。
    created_at: datetime = field(default_factory=utc_now)
    # 后台工作线程真正开始执行的 UTC 时间。
    started_at: datetime | None = None
    # 运行进入终态的 UTC 时间。
    finished_at: datetime | None = None
    # 模型正常完成后允许展示给用户的最终回答。
    final_content: str | None = None
    # 机器可读终止原因。
    reason: str | None = None
    # 运行器未能返回正常结果时的安全错误对象。
    error: dict[str, str] | None = None
    # 实际模型请求次数。
    model_calls: int = 0
    # 实际处理的工具调用次数。
    tool_calls: int = 0
    # 累计 Token 用量安全副本。
    usage: dict[str, int] = field(default_factory=_empty_usage)
    # 运行墙钟耗时，单位为秒。
    duration_seconds: float | None = None
    # 本轮文件修改与最近一次检查的关系。
    change_check: dict[str, Any] = field(default_factory=dict)
    # 工作区记忆加载状态摘要。
    memory: MemorySummary = field(default_factory=lambda: MemorySummary(status="pending"))
    # 当前正在等待的审批；没有审批时为空。
    pending_approval: PendingApproval | None = None
    # 同步工具线程与 HTTP 审批接口之间的桥接器。
    approval_broker: ApprovalBroker | None = None
    # 在线程池中执行本会话的 Future。
    future: Future[None] | None = None
    # ``run.finished`` 是否已经进入事件缓冲区。
    final_event_published: bool = False
    # 外层持久化终态是否已经完成对账。
    durable_finalized: bool = True
    # 保护本会话全部可变字段的一致性锁。
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def summary(self) -> dict[str, Any]:
        """在线程锁内生成供 API 和持久化回调使用的一致快照。"""

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
                "change_check": dict(self.change_check),
                "memory": self.memory.as_dict(),
                "pending_approval": (
                    self.pending_approval.as_dict() if self.pending_approval is not None else None
                ),
                "cancel_requested": self.cancel_event.is_set(),
            }

    @property
    def terminal(self) -> bool:
        """判断会话当前是否已经进入任一终态。

        :return: 状态属于 ``TERMINAL_STATUSES`` 时为 True。
        """

        with self.lock:
            return self.status in TERMINAL_STATUSES

    def mark_running(self) -> bool:
        """在未收到取消信号时将会话标为运行中。

        :return: 成功进入运行状态时为 True，已请求取消时为 False。
        """

        with self.lock:
            if self.cancel_event.is_set():
                return False
            self.status = RunStatus.RUNNING
            self.started_at = utc_now()
            return True

    def set_pending(self, pending: PendingApproval | None) -> None:
        """更新待审批快照并同步调整运行状态。

        :param pending: 新审批快照；``None`` 表示审批等待已结束。
        """

        with self.lock:
            self.pending_approval = pending
            if self.status in TERMINAL_STATUSES or self.status is RunStatus.CANCELLING:
                return
            self.status = RunStatus.WAITING_APPROVAL if pending is not None else RunStatus.RUNNING

    def set_memory(self, memory: MemorySummary) -> None:
        """更新记忆摘要，但保持显式禁用状态不被覆盖。

        :param memory: 运行器报告的最新记忆加载摘要。
        """

        with self.lock:
            if self.memory.status != "disabled":
                self.memory = memory

    def mark_final_event_published(self) -> None:
        """记录最终事件已经进入实时缓冲区。"""

        with self.lock:
            self.final_event_published = True

    def mark_durable_finalized(self) -> None:
        """记录外层持久化终态已经完成对账。"""

        with self.lock:
            self.durable_finalized = True

    @property
    def stream_complete(self) -> bool:
        """判断运行终态及最终流事件是否都已就绪。

        :return: 已进入终态且最终事件已发布时为 True。
        """

        with self.lock:
            return self.status in TERMINAL_STATUSES and self.final_event_published

    @property
    def evictable(self) -> bool:
        """判断会话能否从有限保留缓存安全淘汰。

        :return: 终态、最终事件发布和持久化对账均完成时为 True。
        """

        with self.lock:
            return (
                self.status in TERMINAL_STATUSES
                and self.final_event_published
                and self.durable_finalized
            )

    def request_cancel(self) -> bool:
        """幂等设置取消信号并唤醒可能的审批等待。

        :return: 本次接受了活动运行取消请求时为 True；已终态时为 False。
        """

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
        """把执行器结果归并为 Web 运行终态。

        :param outcome: 同步 Agent 运行器返回的安全结果摘要。
        """

        with self.lock:
            # 第一步：取消信号优先，其次按执行器状态选择最终状态和正文。
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
            # 第二步：复制用量、记忆和完成时间，形成可持久化的完整终态快照。
            self.model_calls = outcome.model_calls
            self.tool_calls = outcome.tool_calls
            self.usage = dict(outcome.usage)
            self.duration_seconds = outcome.duration_seconds
            self.change_check = dict(outcome.change_check)
            if self.memory.status != "disabled":
                self.memory = outcome.memory
            self.pending_approval = None
            self.finished_at = utc_now()

    def fail(self, code: str, message: str) -> None:
        """记录运行器未能返回正常 RunOutcome 时的失败终态。

        :param code: 机器可读失败原因；取消已发生时会被取消语义覆盖。
        :param message: 可持久化并展示的安全错误文本。
        """

        with self.lock:
            # 第一步：如果用户已经请求取消，则取消语义覆盖内部错误。
            if self.cancel_event.is_set():
                self.status = RunStatus.CANCELLED
                self.reason = "user_cancelled"
                self.error = None
            else:
                self.status = RunStatus.FAILED
                self.reason = code
                self.error = {"code": code, "message": message}
            # 第二步：补齐尚未完成的记忆状态并清除悬挂审批。
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
        """初始化进程内运行索引、工作区占位和有界线程池。

        :param runner: 实际装配并同步执行 Agent 的运行器。
        :param workspace_policy: 校验用户选择目录的服务端白名单策略。
        :param max_active_runs: 不同工作区可同时执行的最大运行数量。
        :param max_retained_runs: 进程内最多保留的活动和终态会话总数。
        :param event_buffer_size: 每个运行的内存事件缓冲区容量。
        :param approval_timeout_seconds: 单次工具审批允许等待的最长秒数。
        :param run_deadline_seconds: 可选的审批代理级运行总截止时间。
        """

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
        """判断底层运行器能否接受新任务。

        :return: 模型供应商配置就绪时为 True。
        """

        return bool(self.runner.ready)

    @property
    def model(self) -> str:
        """返回底层运行器配置的模型名称。

        :return: 当前模型 ID。
        """

        return self.runner.model

    @property
    def active_runs(self) -> int:
        """取得当前占用工作区的活动运行数。

        :return: 活动工作区占位映射的条目数量。
        """

        with self._lock:
            return len(self._active_workspaces)

    def validate_workspace(self, value: str) -> Path:
        """校验并规范化用户选择的工作区。

        :param value: 用户提交的工作区绝对路径文本。
        :return: 白名单根目录内的现有规范目录。
        :raises RunManagerError: 工作区不满足服务端白名单策略。
        """

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
        memory_snapshot: tuple[MemoryReference, ...] = (),
        run_id: str | None = None,
        on_event: Callable[[RunEvent], None] | None = None,
        on_finished: Callable[[dict[str, Any]], bool | None] | None = None,
    ) -> dict[str, Any]:
        """校验请求、原子预留工作区，并把运行提交到后台线程池。

        :param workspace: 已选择工作区的绝对路径文本。
        :param task: 当前用户任务正文。
        :param use_memory: 是否允许本次运行使用工作区记忆。
        :param permission_mode: 本次运行冻结的权限模式。
        :param prior_messages: 创建事务中冻结的可见会话历史。
        :param memory_snapshot: PostgreSQL 创建事务中冻结的记忆；空元组表示没有可用记忆。
        :param run_id: 可选外部运行标识；省略时由管理器生成。
        :param on_event: 每次发布安全事件时调用的可选持久化回调。
        :param on_finished: 运行终止后执行持久化对账的可选回调。
        :return: 新建运行的线程安全会话摘要。
        :raises RunManagerError: 输入、容量、工作区占用或服务状态不允许创建运行。
        """

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
        if not isinstance(memory_snapshot, tuple) or not all(
            isinstance(item, MemoryReference) for item in memory_snapshot
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
        """取得一个进程内运行的当前摘要。

        :param run_id: 运行唯一标识。
        :return: 在线程锁内生成的安全状态字典。
        :raises RunManagerError: 运行不存在。
        """

        return self._session(run_id).summary()

    def get_buffer(self, run_id: str) -> EventBuffer:
        """取得运行专属的实时事件缓冲区。

        :param run_id: 运行唯一标识。
        :return: 对应 ``EventBuffer``。
        :raises RunManagerError: 运行不存在。
        """

        return self._session(run_id).buffer

    def is_terminal(self, run_id: str) -> bool:
        """判断运行是否已经进入任一终态。

        :param run_id: 运行唯一标识。
        :return: 运行已完成、失败、取消或预算耗尽时为 ``True``。
        """

        return self._session(run_id).terminal

    def is_stream_complete(self, run_id: str) -> bool:
        """判断运行终态及最终事件是否都已就绪。

        :param run_id: 运行唯一标识。
        :return: SSE 可以安全结束时返回 ``True``。
        """

        return self._session(run_id).stream_complete

    def cancel(self, run_id: str) -> dict[str, Any]:
        """为运行设置协作式取消信号并返回最新摘要。

        :param run_id: 运行唯一标识。
        :return: 发出取消请求后的会话摘要。
        """

        session = self._session(run_id)
        session.request_cancel()
        return session.summary()

    def resolve_approval(self, run_id: str, approval_id: str, decision: str) -> None:
        """把 HTTP 审批决定提交给指定运行的等待线程。

        :param run_id: 审批所属运行标识。
        :param approval_id: 当前待审批请求标识。
        :param decision: ``approve`` 或 ``reject``。
        :raises RunManagerError: 运行、审批或决定状态不合法。
        """

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
        """执行一次变更期间，原子排除同工作区运行。

        :param workspace: 即将修改记忆的工作区绝对路径文本。
        :return: 上下文管理器迭代出的规范工作区路径。
        :raises RunManagerError: 工作区有活动运行、其他记忆变更或服务正在关闭。
        """

        # 第一步：规范化工作区，并在管理器锁内检查运行和其他记忆变更冲突。
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
        # 第二步：调用方持有逻辑预留期间执行数据库变更，结束后始终释放占位。
        try:
            yield resolved_workspace
        finally:
            with self._lock:
                self._memory_mutations.discard(key)

    def validate_memory_source(self, run_id: str, workspace: str) -> None:
        """确认可选运行来源，且不暴露保留的运行内容。

        :param run_id: 用户希望作为记忆来源的已完成运行标识。
        :param workspace: 新记忆所属工作区路径。
        :raises RunManagerError: 来源不存在、跨工作区或未成功完成。
        """

        # 第一步：取得来源会话快照，并把不存在统一映射为记忆领域错误。
        resolved_workspace = self.validate_workspace(workspace)
        try:
            session = self._session(run_id)
        except RunManagerError as exc:
            raise RunManagerError(
                "memory_not_found", "The source run was not found.", status_code=404
            ) from exc
        # 第二步：来源必须属于同一工作区且已经成功完成。
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
        """按从新到旧列出最近的进程内运行摘要。

        :param limit: 希望返回的数量，实际会限制在 1 到 100。
        :return: 最新运行在前的安全摘要列表。
        """

        safe_limit = max(1, min(int(limit), 100))
        with self._lock:
            sessions = tuple(self._sessions.values())[-safe_limit:]
        return [session.summary() for session in reversed(sessions)]

    def shutdown(self, *, wait: bool = False) -> None:
        """停止接收新运行，取消活动会话并关闭线程池。

        :param wait: 是否阻塞等待当前工作线程退出。
        """

        # 第一步：原子切换关闭状态并复制活动运行 ID，避免持锁执行回调。
        with self._lock:
            if self._closing:
                return
            self._closing = True
            active_ids = tuple(self._active_workspaces.values())
        # 第二步：逐个发出协作式取消，最后关闭执行器并拒绝后续提交。
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
        memory_snapshot: tuple[MemoryReference, ...],
    ) -> None:
        """在线程池中执行一个会话，并保证任何退出路径都完成资源收尾。

        :param session: 已登记且占用工作区的运行会话。
        :param task: 当前用户任务正文。
        :param use_memory: 是否启用工作区记忆。
        :param workspace_key: 用于释放活动工作区占位的规范路径键。
        :param prior_messages: 创建事务冻结的可见历史消息。
        :param memory_snapshot: PostgreSQL 创建事务冻结的记忆快照。
        """

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
        """允许已对账的终态会话参与保留淘汰。

        :param run_id: 已完成外层持久化对账的运行标识。
        :raises RunManagerError: 运行不存在。
        """

        self._session(run_id).mark_durable_finalized()

    def _publish_finished(self, session: RunSession) -> None:
        """发布一次统一最终事件并标记实时流可以结束。

        :param session: 已经进入终态的运行会话。
        """

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
                "change_check": summary["change_check"],
            },
        )
        session.mark_final_event_published()

    def _session(self, run_id: str) -> RunSession:
        """从进程内索引取得运行会话。

        :param run_id: 运行唯一标识。
        :return: 对应可变 ``RunSession``。
        :raises RunManagerError: 标识为空或运行不存在。
        """

        if not isinstance(run_id, str) or not run_id:
            raise RunManagerError("run_not_found", "Run was not found.", status_code=404)
        with self._lock:
            session = self._sessions.get(run_id)
        if session is None:
            raise RunManagerError("run_not_found", "Run was not found.", status_code=404)
        return session

    @staticmethod
    def _workspace_key(workspace: Path) -> str:
        """生成工作区并发占位使用的平台路径键。

        :param workspace: 已规范化工作区路径。
        :return: 绝对化并应用平台大小写规则的字符串。
        """

        return os.path.normcase(os.path.abspath(os.fspath(workspace)))

    def _evict_terminal_locked(self) -> None:
        """在管理器锁内淘汰最旧且已完全收尾的会话。"""

        while len(self._sessions) >= self.max_retained_runs:
            evicted = False
            for run_id, session in tuple(self._sessions.items()):
                if session.evictable:
                    self._sessions.pop(run_id, None)
                    evicted = True
                    break
            if not evicted:
                break


__all__ = ["RunManager", "RunManagerError"]
