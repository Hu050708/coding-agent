"""事务级实体仓储。"""

from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.orm import Session

from coding_agent.models import (
    Workspace,
)

from .base import (
    UUIDLike,
    PersistenceNotFoundError,
    _required_text,
    as_uuid,
    utc_now,
)
class WorkspaceRepository:
    """封装工作区表的创建、查询、锁定和归档操作。"""

    def __init__(self, session: Session) -> None:
        """绑定当前业务事务使用的 ORM 会话。

        :param session: 由上层负责提交或回滚的 SQLAlchemy 会话。
        """

        # 仓储不拥有会话生命周期，只在调用方事务内执行查询和 flush。
        self.session = session

    def create(
        self, *, canonical_path: str, path_key: str, display_name: str
    ) -> Workspace:
        """创建一个已由安全策略规范化的工作区。

        :param canonical_path: 工作区的规范绝对路径。
        :param path_key: 用于唯一比较的规范路径键。
        :param display_name: 用户可见的工作区名称。
        :return: 已 flush 并获得主键的工作区实体。
        """

        item = Workspace(
            canonical_path=_required_text(canonical_path, label="canonical_path"),
            path_key=_required_text(path_key, label="path_key", limit=2048),
            display_name=_required_text(display_name, label="display_name", limit=255),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def get(
        self,
        workspace_id: UUIDLike,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> Workspace | None:
        """按 ID 查询工作区，可选择锁定或包含软删除记录。

        :param workspace_id: 工作区 UUID 或其字符串形式。
        :param include_deleted: 是否允许返回已软删除记录。
        :param for_update: 是否为后续修改获取行级写锁。
        :return: 匹配实体；不存在时返回 None。
        """

        statement = select(Workspace).where(Workspace.id == as_uuid(workspace_id))
        if not include_deleted:
            statement = statement.where(Workspace.deleted_at.is_(None))
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def require(self, workspace_id: UUIDLike, *, for_update: bool = False) -> Workspace:
        """读取必须存在的活动工作区。

        :param workspace_id: 工作区 UUID 或其字符串形式。
        :param for_update: 是否获取行级写锁。
        :return: 匹配的活动工作区实体。
        :raises PersistenceNotFoundError: 工作区不存在或已软删除。
        """

        item = self.get(workspace_id, for_update=for_update)
        if item is None:
            raise PersistenceNotFoundError("workspace was not found")
        return item

    def get_by_path_key(self, path_key: str) -> Workspace | None:
        """按规范路径键查找活动工作区。

        :param path_key: 已规范化、用于唯一比较的路径键。
        :return: 匹配的活动工作区；不存在时为 None。
        """

        return self.session.scalar(
            select(Workspace).where(
                Workspace.path_key == _required_text(path_key, label="path_key", limit=2048),
                Workspace.deleted_at.is_(None),
            )
        )

    def list(self, *, include_archived: bool = False) -> list[Workspace]:
        """列出未软删除的工作区。

        :param include_archived: 是否同时返回已归档工作区。
        :return: 按更新时间倒序排列的工作区实体列表。
        """

        statement = select(Workspace).where(Workspace.deleted_at.is_(None))
        if not include_archived:
            statement = statement.where(Workspace.archived_at.is_(None))
        statement = statement.order_by(Workspace.updated_at.desc(), Workspace.display_name)
        return list(self.session.scalars(statement))

    def archive(self, workspace_id: UUIDLike, *, archived: bool = True) -> Workspace:
        """切换工作区归档状态。

        :param workspace_id: 目标工作区 ID。
        :param archived: True 表示归档，False 表示恢复。
        :return: 更新并 flush 后的工作区实体。
        """

        item = self.require(workspace_id, for_update=True)
        item.archived_at = utc_now() if archived else None
        item.updated_at = utc_now()
        self.session.flush()
        return item

    def soft_delete(self, workspace_id: UUIDLike) -> Workspace:
        """软删除并同时归档工作区。

        :param workspace_id: 目标工作区 ID。
        :return: 标记删除后的工作区实体。
        """

        item = self.require(workspace_id, for_update=True)
        now = utc_now()
        item.deleted_at = now
        item.archived_at = item.archived_at or now
        item.updated_at = now
        self.session.flush()
        return item
