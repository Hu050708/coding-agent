from __future__ import annotations

from collections.abc import Callable
import os
from typing import TypeVar

from fastapi import APIRouter, Depends, Query, Response, status

from coding_agent.api.dependencies import get_memory_service, get_run_manager
from coding_agent.api.errors import ApiError
from coding_agent.api.schemas.memories import (
    MemoryCreateRequest,
    MemoryEntryResponse,
    MemoryListResponse,
    MemoryPurgeRequest,
    MemoryPurgeResponse,
    MemoryUpdateRequest,
)
from coding_agent.memory import MemorySource
from coding_agent.memory.service import MemoryService, MemoryServiceError
from coding_agent.runs.run_manager import RunManager


router = APIRouter(prefix="/memories", tags=["memories"])
T = TypeVar("T")


def _service_call(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except MemoryServiceError as exc:
        raise ApiError(exc.status_code, exc.code, exc.message) from exc


@router.get("", response_model=MemoryListResponse)
def list_memories(
    workspace: str = Query(min_length=1, max_length=1024),
    service: MemoryService = Depends(get_memory_service),
) -> dict[str, object]:
    items = _service_call(lambda: service.list(workspace))
    return {"items": [entry.as_dict() for entry in items]}


@router.post("", response_model=MemoryEntryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreateRequest,
    service: MemoryService = Depends(get_memory_service),
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, object]:
    with manager.reserve_memory_mutation(payload.workspace) as workspace:
        canonical_workspace = os.fspath(workspace)
        source = MemorySource.MANUAL
        if payload.source_run_id is not None:
            manager.validate_memory_source(payload.source_run_id, canonical_workspace)
            source = MemorySource.RUN_RESULT
        entry = _service_call(
            lambda: service.create(
                workspace=canonical_workspace,
                kind=payload.kind,
                content=payload.content,
                pinned=payload.pinned,
                source=source,
                source_run_id=payload.source_run_id,
            )
        )
    return entry.as_dict()


@router.patch("/{memory_id}", response_model=MemoryEntryResponse)
def update_memory(
    memory_id: str,
    payload: MemoryUpdateRequest,
    service: MemoryService = Depends(get_memory_service),
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, object]:
    with manager.reserve_memory_mutation(payload.workspace) as workspace:
        entry = _service_call(
            lambda: service.update(
                workspace=os.fspath(workspace),
                memory_id=memory_id,
                kind=payload.kind,
                content=payload.content,
                pinned=payload.pinned,
                enabled=payload.enabled,
            )
        )
    return entry.as_dict()


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: str,
    workspace: str = Query(min_length=1, max_length=1024),
    service: MemoryService = Depends(get_memory_service),
    manager: RunManager = Depends(get_run_manager),
) -> Response:
    with manager.reserve_memory_mutation(workspace) as resolved_workspace:
        _service_call(
            lambda: service.delete(
                workspace=os.fspath(resolved_workspace), memory_id=memory_id
            )
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/purge", response_model=MemoryPurgeResponse)
def purge_memories(
    payload: MemoryPurgeRequest,
    service: MemoryService = Depends(get_memory_service),
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, int]:
    with manager.reserve_memory_mutation(payload.workspace) as workspace:
        deleted_count = _service_call(
            lambda: service.purge(workspace=os.fspath(workspace))
        )
    return {"deleted_count": deleted_count}


__all__ = ["router"]
