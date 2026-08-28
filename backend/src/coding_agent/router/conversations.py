"""提供会话及其持久化消息历史的 HTTP 接口。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from coding_agent.dependencies import get_catalog_service
from coding_agent.schemas import (
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
    return {"items": service.list_conversations(str(workspace_id))}


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
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
    return service.get_conversation(str(conversation_id))


@router.patch("/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdateRequest,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
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
    service.delete_conversation(str(conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: UUID,
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, object]:
    return {"items": service.list_messages(str(conversation_id))}


__all__ = ["router"]
