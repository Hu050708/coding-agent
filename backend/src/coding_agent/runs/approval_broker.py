"""Bridge synchronous command confirmation to asynchronous HTTP decisions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import threading
import time
from typing import Any
from uuid import uuid4

from coding_agent.security import CommandRequest


class ApprovalBrokerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class PendingApproval:
    approval_id: str
    argv: tuple[str, ...]
    cwd: str
    reason: str
    created_at: datetime
    expires_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "reason": self.reason,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
        }


class ApprovalBroker:
    """A callable accepted by ToolRegistry that waits for one REST decision."""

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

    def confirm(self, request: CommandRequest) -> bool:
        effective_timeout = self.timeout_seconds
        if self._run_deadline is not None:
            effective_timeout = min(effective_timeout, self._run_deadline - self._clock())
        if effective_timeout <= 0 or self.cancel_event.is_set():
            return False
        created_at = datetime.now(timezone.utc)
        pending = PendingApproval(
            approval_id=uuid4().hex,
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
                # Tool execution is sequential; a second waiter indicates an invariant violation.
                return False
            self._pending = pending
            self._decision = None

        self._pending_changed(pending)
        self._publish(
            "approval.required",
            {"run_id": self.run_id, "approval": pending.as_dict()},
        )

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
            self._decision = decision
            self._condition.notify_all()

    def pending(self) -> PendingApproval | None:
        with self._condition:
            return self._pending

    def cancel(self) -> None:
        with self._condition:
            self._condition.notify_all()


__all__ = ["ApprovalBroker", "ApprovalBrokerError", "PendingApproval"]
