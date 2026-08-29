"""在服务崩溃或重启后对持久化运行进行状态对账。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from coding_agent.models import ACTIVE_RUN_STATUSES, Approval, ApprovalStatus, Run, RunStatus
from coding_agent.repository.base import utc_now
from coding_agent.repository.event_repo import RunEventRepository


def interrupt_stale_runs(session_factory: sessionmaker[Session]) -> int:
    """原子地将重启前的活动运行和审批标记为终态。

    :param session_factory: 用于开启恢复事务的 SQLAlchemy 会话工厂。
    :return: 本次被标记为中断的遗留运行数量。
    """

    # 第一步：锁定所有遗留活动运行，确保多实例恢复时只有一个事务负责对账。
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
        # 第二步：批量把运行标为 interrupted，并写入统一的重启原因。
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
        # 第三步：取消这些运行尚未处理的审批，避免前端继续显示可操作状态。
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
        # 第四步：为每个运行追加可重放事件，使 SSE 客户端能观察到恢复结果。
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
