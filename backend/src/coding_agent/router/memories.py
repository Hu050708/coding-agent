"""提供以工作区路径为键的兼容版项目记忆接口。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from coding_agent.dependencies import get_workspace_memory_service
from coding_agent.schemas.memories import (
    WorkspaceMemoryCreateRequest,
    WorkspaceMemoryListResponse,
    WorkspaceMemoryPurgeResponse,
    WorkspaceMemoryResponse,
    WorkspaceMemoryUpdateRequest,
)
from coding_agent.services import WorkspaceMemoryService


router = APIRouter(prefix="/workspaces/{workspace_id}/memories", tags=["memory"])


@router.get("", response_model=WorkspaceMemoryListResponse)
def list_memories(
    workspace_id: UUID,
    service: WorkspaceMemoryService = Depends(get_workspace_memory_service),
) -> dict[str, object]:
    """列出工作区长期记忆。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param service: FastAPI 注入的记忆业务服务。
    :return: 记忆列表响应字典。
    """

    return {"items": service.list(str(workspace_id))}


@router.post("", response_model=WorkspaceMemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    workspace_id: UUID,
    payload: WorkspaceMemoryCreateRequest,
    service: WorkspaceMemoryService = Depends(get_workspace_memory_service),
) -> dict[str, object]:
    """创建一条工作区长期记忆。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param payload: 已校验的记忆创建请求体。
    :param service: FastAPI 注入的记忆业务服务。
    :return: 新记忆公开视图。
    """

    return service.create(
        str(workspace_id),
        kind=payload.kind,
        content=payload.content,
        pinned=payload.pinned,
        source_run_id=str(payload.source_run_id) if payload.source_run_id is not None else None,
    )


@router.post("/clear", response_model=WorkspaceMemoryPurgeResponse)
def clear_memories(
    workspace_id: UUID,
    service: WorkspaceMemoryService = Depends(get_workspace_memory_service),
) -> dict[str, int]:
    """清空工作区长期记忆。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param service: FastAPI 注入的记忆业务服务。
    :return: 包含实际删除数量的字典。
    """

    return {"deleted_count": service.purge(str(workspace_id))}


@router.patch("/{memory_id}", response_model=WorkspaceMemoryResponse)
def update_memory(
    workspace_id: UUID,
    memory_id: UUID,
    payload: WorkspaceMemoryUpdateRequest,
    service: WorkspaceMemoryService = Depends(get_workspace_memory_service),
) -> dict[str, object]:
    """部分更新一条工作区记忆。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param memory_id: URL 路径中的记忆 UUID。
    :param payload: 已校验的记忆更新请求体。
    :param service: FastAPI 注入的记忆业务服务。
    :return: 更新后的记忆公开视图。
    """

    return service.update(
        str(workspace_id),
        str(memory_id),
        kind=payload.kind,
        content=payload.content,
        pinned=payload.pinned,
        enabled=payload.enabled,
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    workspace_id: UUID,
    memory_id: UUID,
    service: WorkspaceMemoryService = Depends(get_workspace_memory_service),
) -> Response:
    """删除一条工作区记忆。

    :param workspace_id: URL 路径中的工作区 UUID。
    :param memory_id: URL 路径中的记忆 UUID。
    :param service: FastAPI 注入的记忆业务服务。
    :return: 无正文的 HTTP 204 响应。
    """

    service.delete(str(workspace_id), str(memory_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
