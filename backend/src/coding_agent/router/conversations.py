"""提供会话及其持久化消息历史的 HTTP 接口。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coding_agent.dependencies import get_catalog_service
from coding_agent.schemas.conversations import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageListResponse,
)
from coding_agent.services import CatalogService


router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    workspace_id: UUID = Query(),
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """列出指定工作区的会话。

    :param workspace_id: 查询参数中的工作区 UUID。
    :param service: FastAPI 注入的目录业务服务。
    :return: 符合会话列表响应模型的字典。
    """

    return {"items": service.list_conversations(str(workspace_id))}


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """创建一个会话。

    :param payload: 已校验的会话创建请求体。
    :param service: FastAPI 注入的目录业务服务。
    :return: 新会话公开视图。
    """

    return service.create_conversation(
        workspace_id=str(payload.workspace_id),
        title=payload.title,
        default_permission_mode=payload.default_permission_mode,
        use_memory=payload.use_memory,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """读取一条会话。

    :param conversation_id: URL 路径中的会话 UUID。
    :param service: FastAPI 注入的目录业务服务。
    :return: 会话公开视图。
    """

    return service.get_conversation(str(conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """部分更新会话设置。

    :param conversation_id: URL 路径中的会话 UUID。
    :param payload: 已校验的部分更新请求体。
    :param service: FastAPI 注入的目录业务服务。
    :return: 更新后的会话公开视图。
    """

    return service.update_conversation(
        str(conversation_id),
        title=payload.title,
        default_permission_mode=payload.default_permission_mode,
        use_memory=payload.use_memory,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> Response:
    """删除没有活动运行的会话。

    :param conversation_id: URL 路径中的会话 UUID。
    :param service: FastAPI 注入的目录业务服务。
    :return: 无正文的 HTTP 204 响应。
    """

    service.delete_conversation(str(conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    """列出会话的可见消息历史。

    :param conversation_id: URL 路径中的会话 UUID。
    :param service: FastAPI 注入的目录业务服务。
    :return: 符合消息列表响应模型的字典。
    """

    return {"items": service.list_messages(str(conversation_id))}


__all__ = ["router"]
