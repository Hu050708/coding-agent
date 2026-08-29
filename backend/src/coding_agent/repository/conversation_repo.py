"""事务级实体仓储。"""

from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import Session

from coding_agent.models import (
    Conversation,
    PermissionMode,
)

from .base import (
    UUIDLike,
    PersistenceNotFoundError,
    _required_text,
    as_uuid,
    utc_now,
)
class ConversationRepository:
    """封装会话表及其工作区归属约束。"""

    def __init__(self, session: Session) -> None:
        """绑定当前事务使用的 ORM 会话。

        :param session: 由上层负责事务边界的 SQLAlchemy 会话。
        """

        self.session = session

    def create(
        self,
        *,
        workspace_id: UUIDLike,
        title: str,
        default_permission_mode: PermissionMode | str = PermissionMode.AGENT,
        use_memory: bool = True,
    ) -> Conversation:
        """在指定工作区创建会话。

        :param workspace_id: 会话所属工作区 ID。
        :param title: 非空的用户可见标题。
        :param default_permission_mode: 后续运行采用的默认权限模式。
        :param use_memory: 后续运行默认是否使用项目记忆。
        :return: 已 flush 的新会话实体。
        """

        mode = PermissionMode(default_permission_mode).value
        item = Conversation(
            workspace_id=as_uuid(workspace_id, label="workspace_id"),
            title=_required_text(title, label="title", limit=255),
            default_permission_mode=mode,
            use_memory=bool(use_memory),
            next_message_seq=1,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Conversation | None:
        """按 ID 查询会话并可约束其工作区归属。

        :param conversation_id: 会话 ID。
        :param workspace_id: 可选的所属工作区 ID 限制。
        :param include_deleted: 是否允许返回已软删除会话。
        :param for_update: 是否获取行级写锁。
        :return: 匹配实体；不存在时为 None。
        """

        statement = select(Conversation).where(Conversation.id == as_uuid(conversation_id))
        if workspace_id is not None:
            statement = statement.where(
                Conversation.workspace_id == as_uuid(workspace_id, label="workspace_id")
            )
        if not include_deleted:
            statement = statement.where(Conversation.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        for_update: bool = False,
    ) -> Conversation:
        """读取必须存在且满足工作区约束的活动会话。

        :param conversation_id: 会话 ID。
        :param workspace_id: 可选的所属工作区 ID 限制。
        :param for_update: 是否获取行级写锁。
        :return: 匹配的会话实体。
        :raises PersistenceNotFoundError: 会话不存在、已删除或不属于指定工作区。
        """

        item = self.get(
            conversation_id, workspace_id=workspace_id, for_update=for_update
        )
        if item is None:
            raise PersistenceNotFoundError("conversation was not found")
        return item

    def list(
        self, workspace_id: UUIDLike, *, include_archived: bool = False
    ) -> list[Conversation]:
        """列出工作区中的活动会话。

        :param workspace_id: 所属工作区 ID。
        :param include_archived: 是否包含已归档会话。
        :return: 按最近更新时间倒序排列的会话列表。
        """

        statement = select(Conversation).where(
            Conversation.workspace_id == as_uuid(workspace_id, label="workspace_id"),
            Conversation.deleted_at.is_(None),
        )
        if not include_archived:
            statement = statement.where(Conversation.archived_at.is_(None))
        statement = statement.order_by(
            Conversation.updated_at.desc(), Conversation.created_at.desc()
        )
        return list(self.session.scalars(statement))

    def rename(self, conversation_id: UUIDLike, *, title: str) -> Conversation:
        """仅修改会话标题。

        :param conversation_id: 目标会话 ID。
        :param title: 新的非空标题。
        :return: 更新后的会话实体。
        """

        return self.update(conversation_id, title=title)

    def update(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        title: str | None = None,
        default_permission_mode: PermissionMode | str | None = None,
        use_memory: bool | None = None,
    ) -> Conversation:
        """在同一事务中更新会话可编辑设置。

        :param conversation_id: 目标会话 ID。
        :param workspace_id: 可选的所属工作区约束。
        :param title: 新标题；None 表示不修改。
        :param default_permission_mode: 新默认权限；None 表示不修改。
        :param use_memory: 新默认记忆开关；None 表示不修改。
        :return: 更新并 flush 后的会话实体。
        :raises ValueError: 没有提供任何可更新字段。
        """

        # 第一步：锁定目标会话，并按请求中实际提供的字段进行部分更新。
        if title is None and default_permission_mode is None and use_memory is None:
            raise ValueError("at least one conversation field must be updated")
        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        if title is not None:
            item.title = _required_text(title, label="title", limit=255)
        if default_permission_mode is not None:
            item.default_permission_mode = PermissionMode(default_permission_mode).value
        if use_memory is not None:
            item.use_memory = bool(use_memory)
        # 第二步：统一刷新更新时间，flush 后让调用方拿到最新实体状态。
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def archive(
        self,
        conversation_id: UUIDLike,
        *,
        workspace_id: UUIDLike | None = None,
        archived: bool = True,
    ) -> Conversation:
        """切换会话归档状态。

        :param conversation_id: 目标会话 ID。
        :param workspace_id: 可选的所属工作区约束。
        :param archived: True 表示归档，False 表示恢复。
        :return: 更新后的会话实体。
        """

        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        item.archived_at = utc_now() if archived else None
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(
        self, conversation_id: UUIDLike, *, workspace_id: UUIDLike | None = None
    ) -> Conversation:
        """软删除并同时归档会话。

        :param conversation_id: 目标会话 ID。
        :param workspace_id: 可选的所属工作区约束。
        :return: 标记删除后的会话实体。
        """

        item = self.require(
            conversation_id, workspace_id=workspace_id, for_update=True
        )
        now = utc_now()
        item.deleted_at = now
        item.archived_at = item.archived_at or now
        item.updated_at = now
        self.session.flush()
        return item
