from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from coding_agent.api.dependencies import get_run_manager
from coding_agent.api.errors import ApiError
from coding_agent.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    RunCreateRequest,
    RunListResponse,
    RunSummaryResponse,
)
from coding_agent.runs.event_buffer import RunEvent
from coding_agent.runs.run_manager import RunManager


router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunSummaryResponse, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    payload: RunCreateRequest,
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, object]:
    return manager.create(
        workspace=payload.workspace,
        task=payload.task,
        use_memory=payload.use_memory,
    )


@router.get("", response_model=RunListResponse)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, object]:
    return {"items": manager.list(limit=limit)}


@router.get("/{run_id}", response_model=RunSummaryResponse)
def get_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> dict[str, object]:
    return manager.get(run_id)


@router.post(
    "/{run_id}/cancel",
    response_model=RunSummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_run(run_id: str, manager: RunManager = Depends(get_run_manager)) -> dict[str, object]:
    return manager.cancel(run_id)


@router.post(
    "/{run_id}/approvals/{approval_id}",
    response_model=ApprovalDecisionResponse,
)
def resolve_approval(
    run_id: str,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    manager: RunManager = Depends(get_run_manager),
) -> dict[str, object]:
    manager.resolve_approval(run_id, approval_id, payload.decision)
    return {
        "run_id": run_id,
        "approval_id": approval_id,
        "decision": payload.decision,
        "accepted": True,
    }


def _sse_frame(event: RunEvent) -> str:
    data = json.dumps(event.as_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.event}\ndata: {data}\n\n"


def _reset_frame(sequence: int, run_id: str, status_value: str) -> str:
    envelope = {
        "seq": sequence,
        "event": "stream.reset",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data": {
            "run_id": run_id,
            "status": status_value,
            "message": "Earlier events are no longer retained; refresh run status.",
        },
    }
    data = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return f"id: {sequence}\nevent: stream.reset\ndata: {data}\n\n"


@router.get("/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    manager: RunManager = Depends(get_run_manager),
) -> StreamingResponse:
    # Resolve before returning StreamingResponse so unknown IDs produce a normal JSON 404.
    manager.get(run_id)
    if last_event_id is None or not last_event_id.strip():
        after_sequence = 0
    else:
        try:
            after_sequence = int(last_event_id)
        except ValueError as exc:
            raise ApiError(400, "last_event_id_invalid", "Last-Event-ID must be an integer.") from exc
        if after_sequence < 0:
            raise ApiError(400, "last_event_id_invalid", "Last-Event-ID must be non-negative.")
    buffer = manager.get_buffer(run_id)

    async def generate() -> AsyncIterator[str]:
        sequence = after_sequence
        subscription = buffer.subscribe()
        reset_sent = False
        try:
            while True:
                if await request.is_disconnected():
                    return
                subscription.clear()
                events, gap = buffer.read_after(sequence)
                if gap and not reset_sent:
                    reset_sent = True
                    reset_sequence = max(sequence, events[0].seq - 1 if events else buffer.latest_sequence)
                    current = manager.get(run_id)
                    yield _reset_frame(reset_sequence, run_id, str(current["status"]))
                    sequence = reset_sequence
                for event in events:
                    yield _sse_frame(event)
                    sequence = event.seq
                if manager.is_stream_complete(run_id) and sequence >= buffer.latest_sequence:
                    return
                if events:
                    continue
                notified = await subscription.wait(15.0)
                if not notified:
                    yield ": keep-alive\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
