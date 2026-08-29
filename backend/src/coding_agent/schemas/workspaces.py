"""定义工作区目录管理和文件夹浏览的数据模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from .base import ApiModel

class WorkspaceCreateRequest(ApiModel):
    """登记一个本地工作区的请求体。"""

    # 位于允许根目录中的现有文件夹路径。
    path: str = Field(min_length=1, max_length=1024)
    # 可选的用户可见名称；省略时使用目录名。
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("path")
    @classmethod
    def path_must_not_be_blank(cls, value: str) -> str:
        """清理工作区路径并拒绝纯空白值。

        :param value: 客户端提交的文件夹路径。
        :return: 去除首尾空白后的路径。
        :raises ValueError: 路径只包含空白字符。
        """

        if not value.strip():
            raise ValueError("path may not be blank")
        return value.strip()

    @field_validator("display_name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        """清理可选显示名称并拒绝纯空白值。

        :param value: 客户端提交的显示名称或 None。
        :return: None 或去除首尾空白后的名称。
        :raises ValueError: 名称只包含空白字符。
        """

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("display_name may not be blank")
        return normalized


class WorkspaceResponse(ApiModel):
    """不直接暴露规范绝对路径的工作区响应。"""

    # 工作区 ID。
    id: UUID
    # 用户可见名称。
    display_name: str
    # 仅供识别的安全路径提示。
    path_hint: str | None = None
    # 创建时间。
    created_at: datetime
    # 最近更新时间。
    updated_at: datetime
    # 归档时间；未归档时为 None。
    archived_at: datetime | None = None


class WorkspaceListResponse(ApiModel):
    """已登记工作区列表响应。"""

    # 活动或按查询要求选择的工作区集合。
    items: list[WorkspaceResponse]


class DirectoryEntryResponse(ApiModel):
    """允许根目录下的一个可浏览子目录。"""

    # 子目录名称。
    name: str
    # 传回浏览接口时使用的规范路径。
    path: str
    # 该目录是否可以直接登记为工作区。
    selectable: bool = True


class DirectoryBrowseResponse(ApiModel):
    """安全目录浏览结果。"""

    # 当前正在浏览的规范目录。
    current_path: str
    # 允许边界内的父目录；位于根目录时为 None。
    parent_path: str | None = None
    # 配置允许根目录的安全表示。
    allowed_root: str
    # 当前目录下可访问的子目录。
    entries: list[DirectoryEntryResponse]


__all__ = [
    "DirectoryBrowseResponse",
    "DirectoryEntryResponse",
    "WorkspaceCreateRequest",
    "WorkspaceListResponse",
    "WorkspaceResponse",
]
