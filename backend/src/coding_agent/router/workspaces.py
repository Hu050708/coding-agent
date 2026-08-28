"""提供工作区目录管理和安全的目录浏览接口。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coding_agent.dependencies import get_catalog_service
from coding_agent.schemas import (
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
    return service.browse_directories(path)


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    return {"items": service.list_workspaces()}


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    return service.create_workspace(path=payload.path, display_name=payload.display_name)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> Response:
    service.delete_workspace(str(workspace_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
