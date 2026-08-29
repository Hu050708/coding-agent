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
from coding_agent.schemas.runs import (
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
    """在会话中创建或幂等取得一次 Agent 运行。

    :param conversation_id: URL 路径中的会话 UUID。
    :param payload: 已校验的运行创建请求体。
    :param service: FastAPI 注入的运行业务服务。
    :return: 运行公开投影。
    """

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
    """读取运行的最新公开投影。

    :param run_id: URL 路径中的运行 UUID。
    :param service: FastAPI 注入的运行业务服务。
    :return: 对账后的运行公开投影。
    """

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
    """请求取消活动运行。

    :param run_id: URL 路径中的运行 UUID。
    :param service: FastAPI 注入的运行业务服务。
    :return: 取消请求后的运行投影。
    """

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
    """处理运行中的待审批工具操作。

    :param run_id: URL 路径中的运行 UUID。
    :param approval_id: URL 路径中的审批 UUID。
    :param payload: 已校验的同意或拒绝决定。
    :param service: FastAPI 注入的运行业务服务。
    :return: 审批决定接受确认。
    """

    return service.resolve_approval(str(run_id), str(approval_id), payload.decision)


def _sse_frame(event: RunEventRecord) -> str:
    """把持久化事件编码为一个完整 SSE 帧。

    :param event: 已白名单化的持久化运行事件。
    :return: 包含 id、event 和 JSON data 行的 SSE 文本。
    """

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
    """从客户端已确认的位置开始，持续输出可恢复的运行事件流。

    :param run_id: URL 路径中的运行 UUID。
    :param request: 当前 FastAPI 请求，用于检测客户端断开。
    :param after_seq: 查询参数提供的断点续传序号。
    :param last_event_id: 浏览器通过请求头提供的最后已接收事件 ID。
    :param service: FastAPI 注入的运行业务服务。
    :return: ``text/event-stream`` 流式响应。
    :raises ApiError: Last-Event-ID 不是非负整数。
    """

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
        """按游标持续产出数据库事件，并用内存通知降低轮询延迟。

        :return: 异步产生的 SSE 帧序列。
        """

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
