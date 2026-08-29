"""事务级实体仓储。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from coding_agent.models import (
    PermissionMode,
    Run,
    RunStatus,
)

from .base import (
    UUIDLike,
    PersistenceConflictError,
    PersistenceNotFoundError,
    _required_text,
    _validate_run_transition,
    as_uuid,
    utc_now,
)
class RunRepository:
    """封装运行状态机、活动运行查询和终态结果写入。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务使用的 ORM 会话。

        :param session: 由上层负责事务边界的 SQLAlchemy 会话。
        """

        self.session = session

    def create(
        self,
        *,
        workspace_id: UUIDLike,
        conversation_id: UUIDLike,
        client_request_id: str,
        permission_mode: PermissionMode | str,
        use_memory: bool,
        model: str | None = None,
        run_id: UUIDLike | None = None,
    ) -> Run:
        """创建处于 starting 状态的 Agent 运行记录。

        :param workspace_id: 本次运行作用的工作区 ID。
        :param conversation_id: 本次运行所属会话 ID。
        :param client_request_id: 会话内唯一的客户端幂等请求标识。
        :param permission_mode: 本次运行采用的权限模式。
        :param use_memory: 本次运行是否装载项目记忆。
        :param model: 可选的实际模型名称。
        :param run_id: 可选的预分配运行 ID，用于和内存运行时对齐。
        :return: 已 flush 且处于 starting 状态的运行实体。
        """

        # 第一步：固化本次运行使用的工作区、会话、权限和记忆开关。
        item = Run(
            workspace_id=as_uuid(workspace_id, label="workspace_id"),
            conversation_id=as_uuid(conversation_id, label="conversation_id"),
            client_request_id=_required_text(
                client_request_id, label="client_request_id", limit=128
            ),
            permission_mode=PermissionMode(permission_mode).value,
            use_memory=bool(use_memory),
            status=RunStatus.STARTING.value,
            model=(None if model is None else _required_text(model, label="model", limit=255)),
        )
        if run_id is not None:
            item.id = as_uuid(run_id, label="run_id")
        # 第二步：flush 使运行编号可立即用于消息、事件和审批等关联记录。
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self, run_id: UUIDLike, *, include_deleted: bool = False, for_update: bool = False
    ) -> Run | None:
        """按 ID 查询运行。

        :param run_id: 运行 ID。
        :param include_deleted: 是否允许返回已软删除运行。
        :param for_update: 是否获取行级写锁。
        :return: 匹配实体；不存在时为 None。
        """

        statement = select(Run).where(Run.id == as_uuid(run_id, label="run_id"))
        if not include_deleted:
            statement = statement.where(Run.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(self, run_id: UUIDLike, *, for_update: bool = False) -> Run:
        """读取必须存在的活动运行。

        :param run_id: 运行 ID。
        :param for_update: 是否获取行级写锁。
        :return: 匹配的运行实体。
        :raises PersistenceNotFoundError: 运行不存在或已软删除。
        """

        item = self.get(run_id, for_update=for_update)
        if item is None:
            raise PersistenceNotFoundError("run was not found")
        return item

    def get_by_request(
        self, conversation_id: UUIDLike, client_request_id: str
    ) -> Run | None:
        """按会话和客户端请求标识查询幂等运行。

        :param conversation_id: 会话 ID。
        :param client_request_id: 客户端幂等请求标识。
        :return: 已有运行；不存在时为 None。
        """

        return self.session.scalar(
            select(Run).where(
                Run.conversation_id == as_uuid(conversation_id, label="conversation_id"),
                Run.client_request_id
                == _required_text(client_request_id, label="client_request_id", limit=128),
            )
        )

    def active_for_workspace(self, workspace_id: UUIDLike) -> Run | None:
        """查询工作区当前唯一的非终态运行。

        :param workspace_id: 工作区 ID。
        :return: 活动运行实体；没有时为 None。
        """

        return self.session.scalar(
            select(Run).where(
                Run.workspace_id == as_uuid(workspace_id, label="workspace_id"),
                Run.status.in_(
                    [
                        RunStatus.STARTING.value,
                        RunStatus.RUNNING.value,
                        RunStatus.WAITING_APPROVAL.value,
                        RunStatus.CANCELLING.value,
                    ]
                ),
                Run.deleted_at.is_(None),
            )
        )

    def set_status(
        self,
        run_id: UUIDLike,
        status: RunStatus | str,
        *,
        reason: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> Run:
        """校验运行状态机并更新状态及相关时间字段。

        :param run_id: 目标运行 ID。
        :param status: 目标运行状态。
        :param reason: 可选的正常终止或取消原因。
        :param error_code: 可选的稳定错误码。
        :param error_message: 可选的安全错误说明。
        :param started_at: 可选的实际开始时间。
        :param finished_at: 可选的明确完成时间。
        :return: 更新后的运行实体。
        :raises PersistenceConflictError: 状态迁移不合法。
        """

        # 第一步：锁定运行并拒绝状态机未允许的跳转。
        item = self.require(run_id, for_update=True)
        value = RunStatus(status)
        _validate_run_transition(RunStatus(item.status), value)
        item.status = value.value
        item.reason = reason[:128] if reason else None
        item.error_code = error_code[:128] if error_code else None
        item.error_message = error_message[:2000] if error_message else None
        if started_at is not None:
            item.started_at = started_at
        if finished_at is not None:
            item.finished_at = finished_at
        elif value not in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            # 进入任意终态时，如调用方未指定时间则由仓储记录当前完成时间。
            item.finished_at = utc_now()
        # 第二步：统一更新时间并刷新当前事务。
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def update_result(
        self,
        run_id: UUIDLike,
        *,
        status: RunStatus | str,
        reason: str | None,
        model_calls: int,
        tool_calls: int,
        usage: Mapping[str, int],
        duration_ms: int | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Run:
        """校验终态转换和计数器后，将完整运行结果写入锁定记录。

        :param run_id: 目标运行 ID。
        :param status: 必须为终态的运行结果状态。
        :param reason: 可选终止原因。
        :param model_calls: 完成的模型调用次数。
        :param tool_calls: 尝试的工具调用次数。
        :param usage: 各类 token 计数映射。
        :param duration_ms: 总运行耗时（毫秒）。
        :param error_code: 可选失败错误码。
        :param error_message: 可选安全失败说明。
        :return: 写入完整结果后的运行实体。
        :raises ValueError: 状态不是终态或计数、耗时非法。
        :raises PersistenceConflictError: 当前状态不能迁移到目标终态。
        """

        # 第一步：锁定运行并确认目标状态是合法终态转换。
        item = self.require(run_id, for_update=True)
        value = RunStatus(status)
        if value in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            raise ValueError("run result status must be terminal")
        _validate_run_transition(RunStatus(item.status), value)
        # 第二步：统一校验所有用量计数和耗时均为非负整数。
        counters = {
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "prompt_cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
            "prompt_cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counters.values()
        ):
            raise ValueError("run result counters must be non-negative integers")
        if duration_ms is not None and (
            isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms < 0
        ):
            raise ValueError("duration_ms must be a non-negative integer")
        # 第三步：截断公开原因和错误文本，设置完成时间后刷新事务。
        for name, counter in counters.items():
            setattr(item, name, counter)
        item.duration_ms = duration_ms
        item.status = value.value
        item.reason = reason[:128] if reason else None
        item.error_code = error_code[:128] if error_code else None
        item.error_message = error_message[:2000] if error_message else None
        item.finished_at = utc_now()
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def request_cancel(self, run_id: UUIDLike) -> Run:
        """将活动运行标为取消中并记录首次取消时间。

        :param run_id: 目标运行 ID。
        :return: 更新后的运行实体。
        :raises PersistenceConflictError: 运行已经进入终态。
        """

        item = self.require(run_id, for_update=True)
        current = RunStatus(item.status)
        if current not in {
            RunStatus.STARTING,
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.CANCELLING,
        }:
            raise PersistenceConflictError("run is already terminal")
        if current is not RunStatus.CANCELLING:
            item.status = RunStatus.CANCELLING.value
        if item.cancel_requested_at is None:
            item.cancel_requested_at = utc_now()
        item.updated_at = utc_now()
        self.session.flush()
        return item
