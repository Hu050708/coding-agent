"""供服务器发送事件使用的线程安全可重放事件缓冲区。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading
from typing import Any


def utc_now() -> datetime:
    """:return: 带 UTC 时区信息的当前时间。"""

    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RunEvent:
    """事件缓冲区中一条带严格递增序号的不可变运行事件。"""

    # 当前缓冲区内严格递增的事件序号。
    seq: int
    # 面向 HTTP/SSE 消费者的事件名称。
    event: str
    # 事件创建时的 UTC 时间。
    timestamp: datetime
    # 已完成 JSON 防御性复制的公开事件数据。
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """把事件转换为适合实时 API 使用的字典。

        :return: 含序号、类型、UTC 时间文本和数据的独立字典。
        """

        return {
            "seq": self.seq,
            "event": self.event,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "data": self.data,
        }


class EventSubscription:
    """把工作线程发布通知桥接到单个 asyncio 事件循环。"""

    def __init__(
        self,
        owner: "EventBuffer",
        token: int,
        signal: asyncio.Event,
    ) -> None:
        """创建绑定到当前异步事件循环的事件订阅。

        :param owner: 拥有订阅者注册表的事件缓冲区。
        :param token: 缓冲区分配的内部订阅标识。
        :param signal: 发布线程用来唤醒异步消费者的事件对象。
        """

        self._owner = owner
        self._token = token
        self._signal = signal
        self._closed = False

    async def wait(self, timeout_seconds: float) -> bool:
        """等待新事件通知或超时。

        :param timeout_seconds: 最多等待的秒数。
        :return: 收到通知时返回 ``True``，超时返回 ``False``。
        """

        try:
            await asyncio.wait_for(self._signal.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return False
        return True

    def clear(self) -> None:
        """清除当前通知标记，准备等待下一次发布。"""

        self._signal.clear()

    def close(self) -> None:
        """幂等关闭订阅并从所属缓冲区取消注册。"""

        if not self._closed:
            self._closed = True
            self._owner._unsubscribe(self._token)


class EventBuffer:
    """支持线程到异步通知的有界只追加日志。"""

    def __init__(
        self,
        max_events: int = 256,
        *,
        on_publish: Callable[[RunEvent], None] | None = None,
    ) -> None:
        """创建有容量上限且支持跨线程通知的事件日志。

        :param max_events: 内存中最多保留的最新事件数量。
        :param on_publish: 可选同步持久化回调，在通知订阅者之前执行。
        :raises ValueError: 事件容量不是正整数。
        """

        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._events: deque[RunEvent] = deque(maxlen=max_events)
        self._next_sequence = 1
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        self._next_subscriber = 1
        self._lock = threading.Lock()
        self._on_publish = on_publish
        self._callback_errors = 0

    def publish(self, event: str, data: Mapping[str, Any] | None = None) -> RunEvent:
        """按严格序号发布事件，并在通知订阅者前调用外部持久化回调。

        :param event: 非空公开事件名称。
        :param data: 必须可严格 JSON 序列化的可选事件数据。
        :return: 已进入缓冲区的不可变 ``RunEvent``。
        :raises ValueError: 事件名为空或数据不能安全序列化。
        """

        if not isinstance(event, str) or not event:
            raise ValueError("event must be non-empty text")
        # 第一步：通过 JSON 往返生成防御性副本，同时拒绝无法序列化的值。
        safe_data = json.loads(
            json.dumps(dict(data or {}), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )
        with self._lock:
            item = RunEvent(self._next_sequence, event, utc_now(), safe_data)
            self._next_sequence += 1
            self._events.append(item)
            # 第二步：序号分配和持久化回调放在同一临界区串行执行，使数据库重放顺序
            # 与实时 SSE 完全一致；集成回调必须自行处理存储错误，且不能反向调用缓冲区。
            if self._on_publish is not None:
                try:
                    self._on_publish(item)
                except Exception:
                    # 持久化属于外部集成，瞬时失败不能占住内存生命周期锁，也不能阻止取消或收尾。
                    self._callback_errors += 1
            subscribers = tuple(self._subscribers.values())
        for loop, signal in subscribers:
            try:
                loop.call_soon_threadsafe(signal.set)
            except RuntimeError:
                # 订阅者循环已经开始关闭，无需再次通知。
                continue
        return item

    def read_after(self, sequence: int) -> tuple[tuple[RunEvent, ...], bool]:
        """读取指定序号之后仍保留在内存中的事件。

        :param sequence: 客户端最后成功处理的非负事件序号。
        :return: 后续事件元组及是否因缓冲区淘汰产生重放缺口。
        :raises ValueError: 序号不是非负整数。
        """

        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        with self._lock:
            events = tuple(self._events)
        if not events:
            return (), False
        gap = sequence < events[0].seq - 1
        return tuple(item for item in events if item.seq > sequence), gap

    @property
    def latest_sequence(self) -> int:
        """取得最近一次发布的事件序号。

        :return: 尚未发布事件时为 0，否则为最大已分配序号。
        """

        with self._lock:
            return self._next_sequence - 1

    @property
    def callback_errors(self) -> int:
        """取得尚未确认修复的外部回调失败次数。

        :return: 自上次确认以来累计的失败计数。
        """

        with self._lock:
            return self._callback_errors

    def acknowledge_callback_errors(self) -> int:
        """持久化修复后清零并返回回调失败次数。

        :return: 清零前累计的回调失败次数。
        """

        with self._lock:
            previous = self._callback_errors
            self._callback_errors = 0
            return previous

    def subscribe(self) -> EventSubscription:
        """为当前异步事件循环创建实时发布订阅。

        :return: 可等待、清除并关闭的订阅对象。
        :raises RuntimeError: 当前线程没有正在运行的 asyncio 事件循环。
        """

        loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        with self._lock:
            token = self._next_subscriber
            self._next_subscriber += 1
            self._subscribers[token] = (loop, signal)
        return EventSubscription(self, token, signal)

    def _unsubscribe(self, token: int) -> None:
        """移除一个内部订阅者注册项。

        :param token: 创建订阅时分配的内部标识。
        """

        with self._lock:
            self._subscribers.pop(token, None)


__all__ = ["EventBuffer", "EventSubscription", "RunEvent", "utc_now"]
