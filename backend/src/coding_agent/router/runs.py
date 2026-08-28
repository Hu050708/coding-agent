"""提供运行生命周期接口以及可恢复的 SSE 事件流。"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse

from coding_agent.dependencies import get_conversation_run_service
from coding_agent.router.errors import ApiError
from coding_agent.schemas import (
    ConversationRunCreateRequest,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    RunResponse,
)
from coding_agent.services import ConversationRunService
from coding_agent.repository import RunEventRecord


router = APIRouter(tags=["runs"])


@router.post(
    "/conversations/{conversation_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_run(
    conversation_id: UUID,
    payload: ConversationRunCreateRequest,
    service: ConversationRunService = Depends(get_conversation_run_service),
) -> dict[str, object]:
    return service.create(
        str(conversation_id),
        content=payload.content,
        permission_mode=payload.permission_mode,
        use_memory=payload.use_memory,
        client_request_id=str(payload.client_request_id),
    )


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: UUID,
    service: ConversationRunService = Depends(get_conversation_run_service),
) -> dict[str, object]:
    return service.get(str(run_id))


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def cancel_run(
    run_id: UUID,
    service: ConversationRunService = Depends(get_conversation_run_service),
) -> dict[str, object]:
    return service.cancel(str(run_id))


@router.post(
    "/runs/{run_id}/approvals/{approval_id}",
    response_model=ApprovalDecisionResponse,
)
def resolve_approval(
    run_id: UUID,
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    service: ConversationRunService = Depends(get_conversation_run_service),
) -> dict[str, object]:
    return service.resolve_approval(str(run_id), str(approval_id), payload.decision)


def _sse_frame(event: RunEventRecord) -> str:
    envelope = {
        "seq": event.seq,
        "event": event.event,
        "timestamp": event.occurred_at.isoformat().replace("+00:00", "Z"),
        "data": event.data,
    }
    data = json.dumps(envelope, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return f"id: {event.seq}\nevent: {event.event}\ndata: {data}\n\n"


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: UUID,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    service: ConversationRunService = Depends(get_conversation_run_service),
) -> StreamingResponse:
    """从客户端已确认的位置开始，持续输出可恢复的运行事件流。"""

    # 第一步：确认运行存在，并合并查询参数与 Last-Event-ID 两种续传游标。
    run_id_value = str(run_id)
    service.get(run_id_value)
    sequence = after_seq
    if last_event_id is not None and last_event_id.strip():
        try:
            header_sequence = int(last_event_id)
        except ValueError as exc:
            raise ApiError(
                400, "last_event_id_invalid", "Last-Event-ID must be an integer."
            ) from exc
        if header_sequence < 0:
            raise ApiError(
                400, "last_event_id_invalid", "Last-Event-ID must be non-negative."
            )
        sequence = max(sequence, header_sequence)

    async def generate() -> AsyncIterator[str]:
        # 第二步：优先读取数据库中的持久化事件，保证重连后不依赖内存缓冲区。
        current = sequence
        terminal_observed = False
        buffer = service.live_buffer(run_id_value)
        subscription = buffer.subscribe() if buffer is not None else None
        try:
            while True:
                if await request.is_disconnected():
                    return
                if subscription is not None:
                    subscription.clear()
                events = await asyncio.to_thread(
                    service.event_records, run_id_value, after_seq=current
                )
                for event in events:
                    yield _sse_frame(event)
                    current = event.seq
                if events:
                    # 单页事件数量有上限，必须先取完下一页，才能判断终态事件已全部发送。
                    continue
                if await asyncio.to_thread(service.is_terminal, run_id_value):
                    if terminal_observed:
                        return
                    # 第三步：终态投影和最终事件使用不同事务，再确认一次空读取，
                    # 避免“读到空页后才写入最终事件”的竞态导致最后一帧丢失。
                    terminal_observed = True
                    continue
                terminal_observed = False
                if subscription is None:
                    # 运行不在本进程时退化为短轮询，并尝试重新接入内存通知。
                    await asyncio.sleep(0.25)
                    buffer = service.live_buffer(run_id_value)
                    if buffer is not None:
                        subscription = buffer.subscribe()
                    continue
                if not await subscription.wait(15.0):
                    # 第四步：空闲期间发送注释帧，防止代理或浏览器关闭长连接。
                    yield ": keep-alive\n\n"
        finally:
            # 无论客户端断开还是运行结束，都释放缓冲区订阅。
            if subscription is not None:
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
