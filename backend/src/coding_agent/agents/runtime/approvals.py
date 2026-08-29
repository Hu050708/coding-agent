"""在同步命令确认和异步 HTTP 审批决定之间建立桥接。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import threading
import time
from typing import Any
from uuid import uuid4

from coding_agent.agents.security import ToolApprovalRequest


class ApprovalBrokerError(RuntimeError):
    """审批决定与当前等待状态冲突时抛出。"""

    def __init__(self, code: str, message: str) -> None:
        """创建可映射到 HTTP 冲突响应的审批错误。

        :param code: 稳定机器可读错误码。
        :param message: 可安全展示给用户的错误说明。
        """

        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PendingApproval:
    """一次正在等待用户决定的不可变审批快照。"""

    # 审批请求唯一标识。
    approval_id: str
    # 发起审批的工具名称。
    tool_name: str
    # 面向用户的安全操作摘要。
    action_summary: str
    # 命令工具的原始参数；非命令工具通常为空。
    argv: tuple[str, ...]
    # 命令执行目录展示值。
    cwd: str
    # 请求审批的策略原因。
    reason: str
    # 审批创建 UTC 时间。
    created_at: datetime
    # 审批自动过期 UTC 时间。
    expires_at: datetime

    def as_dict(self) -> dict[str, Any]:
        """把待审批快照转换为可发布的安全字典。

        :return: 含规范 UTC 时间文本和 argv 列表的独立对象。
        """

        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "action_summary": self.action_summary,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "reason": self.reason,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
        }


class ApprovalBroker:
    """供 ToolRegistry 调用并等待一次 REST 审批决定。"""

    def __init__(
        self,
        *,
        run_id: str,
        cancel_event: threading.Event,
        timeout_seconds: float,
        run_deadline_seconds: float | None = None,
        publish: Callable[[str, Mapping[str, Any]], Any],
        pending_changed: Callable[[PendingApproval | None], Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """保存运行级回调，并建立审批等待所需的条件变量。

        :param run_id: 审批所属运行的唯一标识。
        :param cancel_event: 运行取消时由外部设置的线程事件。
        :param timeout_seconds: 单次审批允许等待的最长秒数。
        :param run_deadline_seconds: 从创建代理起计算的可选运行总截止秒数。
        :param publish: 向运行事件缓冲区发布审批事件的回调。
        :param pending_changed: 同步更新会话待审批快照的回调。
        :param clock: 提供单调时间的函数，主要用于测试注入。
        :raises ValueError: 任一超时不是有限正数。
        """

        self.run_id = run_id
        self.cancel_event = cancel_event
        if not math.isfinite(float(timeout_seconds)) or float(timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if run_deadline_seconds is not None and (
            not math.isfinite(float(run_deadline_seconds)) or float(run_deadline_seconds) <= 0
        ):
            raise ValueError("run_deadline_seconds must be positive and finite")
        self.timeout_seconds = float(timeout_seconds)
        self._publish = publish
        self._pending_changed = pending_changed
        self._clock = clock
        self._run_deadline = (
            None if run_deadline_seconds is None else clock() + float(run_deadline_seconds)
        )
        self._condition = threading.Condition()
        self._pending: PendingApproval | None = None
        self._decision: str | None = None

    def confirm(self, request: ToolApprovalRequest) -> bool:
        """发布审批请求并阻塞等待决定、取消、超时或运行截止时间。

        :param request: 工具层生成的用户可见审批请求。
        :return: 用户在有效期内批准时返回 ``True``，其他终态返回 ``False``。
        """

        # 第一步：规范化审批 ID，并确保同一运行同一时刻只有一个等待者。
        effective_timeout = self.timeout_seconds
        if self._run_deadline is not None:
            effective_timeout = min(effective_timeout, self._run_deadline - self._clock())
        if effective_timeout <= 0 or self.cancel_event.is_set():
            return False
        created_at = datetime.now(timezone.utc)
        pending = PendingApproval(
            # 保持 HTTP 路径转换器和 PostgreSQL UUID 列使用的规范写法；32 位十六进制
            # 虽然等价，但到达这里前 FastAPI 会将其规范化为带连字符形式。
            approval_id=str(uuid4()),
            tool_name=request.tool_name,
            action_summary=request.action_summary,
            argv=request.argv,
            cwd=str(request.cwd),
            reason=request.reason,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=effective_timeout),
        )
        with self._condition:
            if self.cancel_event.is_set():
                return False
            if self._pending is not None:
                # 工具调用按顺序执行，出现第二个等待者说明内部不变量已被破坏。
                return False
            self._pending = pending
            self._decision = None

        # 第二步：先更新会话快照，再广播审批事件供 HTTP/SSE 层持久化和展示。
        self._pending_changed(pending)
        self._publish(
            "approval.required",
            {"run_id": self.run_id, "approval": pending.as_dict()},
        )

        # 第三步：在条件变量上等待 REST 决定，并定期检查取消和超时。
        deadline = self._clock() + effective_timeout
        with self._condition:
            while self._decision is None and not self.cancel_event.is_set():
                remaining = deadline - self._clock()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=min(remaining, 0.5))
            if self.cancel_event.is_set():
                outcome = "cancelled"
            elif self._decision is None:
                outcome = "expired"
            else:
                outcome = self._decision
            approved = outcome == "approve"
            self._pending = None
            self._decision = None

        # 第四步：清除一次性等待状态，并发布统一的审批终态事件。
        self._pending_changed(None)
        self._publish(
            "approval.resolved",
            {
                "run_id": self.run_id,
                "approval_id": pending.approval_id,
                "decision": "approve" if outcome == "approve" else "reject",
                "resolution": outcome,
            },
        )
        return approved

    def resolve(self, approval_id: str, decision: str) -> None:
        """提交一次审批决定，并唤醒正在等待的工具线程。

        :param approval_id: HTTP 调用方正在处理的审批请求标识。
        :param decision: 只允许 ``approve`` 或 ``reject``。
        :raises ApprovalBrokerError: 决定非法、审批不存在、过期、重复或运行取消中。
        """

        # 第一步：校验决定值和审批 ID，拒绝过期或重复提交。
        if decision not in {"approve", "reject"}:
            raise ApprovalBrokerError("approval_decision_invalid", "Decision must be approve or reject.")
        with self._condition:
            pending = self._pending
            if pending is None:
                raise ApprovalBrokerError("approval_not_pending", "There is no pending approval.")
            if pending.approval_id != approval_id:
                raise ApprovalBrokerError("approval_stale", "The approval request is stale.")
            if self._decision is not None:
                raise ApprovalBrokerError("approval_already_resolved", "The approval was already resolved.")
            if self.cancel_event.is_set():
                raise ApprovalBrokerError("run_cancelling", "The run is already cancelling.")
            # 第二步：在同一条件锁内保存决定并通知等待者，避免丢失唤醒。
            self._decision = decision
            self._condition.notify_all()

    def pending(self) -> PendingApproval | None:
        """在线程锁保护下读取当前待审批快照。

        :return: 当前审批；没有等待者时为 None。
        """

        with self._condition:
            return self._pending

    def cancel(self) -> None:
        """唤醒审批等待线程，使其重新检查运行取消事件。"""

        with self._condition:
            self._condition.notify_all()


__all__ = ["ApprovalBroker", "ApprovalBrokerError", "PendingApproval"]
