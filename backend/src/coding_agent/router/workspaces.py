"""提供工作区目录管理和安全的目录浏览接口。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coding_agent.dependencies import get_catalog_service
from coding_agent.schemas.workspaces import (
    DirectoryBrowseResponse,
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
)
from coding_agent.services import CatalogService


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/browse", response_model=DirectoryBrowseResponse)
def browse_directories(
    path: str | None = Query(default=None, max_length=1024),
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """浏览允许根目录内的文件夹。

    :param path: 可选查询目录；省略时从允许根目录开始。
    :param service: FastAPI 注入的目录业务服务。
    :return: 安全目录浏览结果。
    """

    return service.browse_directories(path)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """列出已登记工作区。

    :param service: FastAPI 注入的目录业务服务。
    :return: 工作区列表响应字典。
    """

    return {"items": service.list_workspaces()}


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """登记一个本地目录为工作区。

    :param payload: 已校验的工作区创建请求体。
    :param service: FastAPI 注入的目录业务服务。
    :return: 新工作区公开视图。
    """

    return service.create_workspace(path=payload.path, display_name=payload.display_name)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> Response:
    """删除没有活动运行的工作区登记。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param service: FastAPI 注入的目录业务服务。
    :return: 无正文的 HTTP 204 响应。
    """

    service.delete_workspace(str(workspace_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
