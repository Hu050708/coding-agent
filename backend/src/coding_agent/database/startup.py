"""在服务崩溃或重启后对持久化运行进行状态对账。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from coding_agent.models import ACTIVE_RUN_STATUSES, Approval, ApprovalStatus, Run, RunStatus
from coding_agent.repository.repositories import RunEventRepository, utc_now


def interrupt_stale_runs(session_factory: sessionmaker[Session]) -> int:
    """原子地将重启前的活动运行和审批标记为终态。"""

    now = utc_now()
    active_values = [item.value for item in ACTIVE_RUN_STATUSES]
    with session_factory.begin() as session:
        run_ids = list(
            session.scalars(
                select(Run.id)
                .where(
                    Run.status.in_(active_values),
                    Run.deleted_at.is_(None),
                )
                .with_for_update()
            )
        )
        if not run_ids:
            return 0
        session.execute(
            update(Run)
            .where(Run.id.in_(run_ids))
            .values(
                status=RunStatus.INTERRUPTED.value,
                reason="server_restart",
                error_code="run_interrupted",
                error_message="The server restarted before this run finished.",
                finished_at=now,
                updated_at=now,
            )
        )
        session.execute(
            update(Approval)
            .where(
                Approval.run_id.in_(run_ids),
                Approval.status == ApprovalStatus.PENDING.value,
            )
            .values(
                status=ApprovalStatus.CANCELLED.value,
                resolved_at=now,
                updated_at=now,
            )
        )
        events = RunEventRepository(session)
        for run_id in run_ids:
            events.append_safe_event(
                run_id,
                seq=events.next_sequence(run_id),
                event="run.interrupted",
                timestamp=now,
                data={
                    "run_id": str(run_id),
                    "status": RunStatus.INTERRUPTED.value,
                    "reason": "server_restart",
                },
            )
        return len(run_ids)


__all__ = ["interrupt_stale_runs"]
