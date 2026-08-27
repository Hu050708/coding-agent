"""Thread-safe, replayable event buffer for Server-Sent Events."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RunEvent:
    seq: int
    event: str
    timestamp: datetime
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "event": self.event,
            "timestamp": self.timestamp.isoformat().replace("+00:00", "Z"),
            "data": self.data,
        }


class EventSubscription:
    def __init__(
        self,
        owner: "EventBuffer",
        token: int,
        signal: asyncio.Event,
    ) -> None:
        self._owner = owner
        self._token = token
        self._signal = signal
        self._closed = False

    async def wait(self, timeout_seconds: float) -> bool:
        try:
            await asyncio.wait_for(self._signal.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return False
        return True

    def clear(self) -> None:
        self._signal.clear()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._owner._unsubscribe(self._token)


class EventBuffer:
    """A bounded append-only log with thread-to-async notifications."""

    def __init__(self, max_events: int = 256) -> None:
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._events: deque[RunEvent] = deque(maxlen=max_events)
        self._next_sequence = 1
        self._subscribers: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        self._next_subscriber = 1
        self._lock = threading.Lock()

    def publish(self, event: str, data: Mapping[str, Any] | None = None) -> RunEvent:
        if not isinstance(event, str) or not event:
            raise ValueError("event must be non-empty text")
        # Round-tripping provides a defensive copy and rejects non-JSON values.
        safe_data = json.loads(
            json.dumps(dict(data or {}), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )
        with self._lock:
            item = RunEvent(self._next_sequence, event, utc_now(), safe_data)
            self._next_sequence += 1
            self._events.append(item)
            subscribers = tuple(self._subscribers.values())
        for loop, signal in subscribers:
            try:
                loop.call_soon_threadsafe(signal.set)
            except RuntimeError:
                # The subscriber loop is already shutting down.
                continue
        return item

    def read_after(self, sequence: int) -> tuple[tuple[RunEvent, ...], bool]:
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
        with self._lock:
            return self._next_sequence - 1

    def subscribe(self) -> EventSubscription:
        loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        with self._lock:
            token = self._next_subscriber
            self._next_subscriber += 1
            self._subscribers[token] = (loop, signal)
        return EventSubscription(self, token, signal)

    def _unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)


__all__ = ["EventBuffer", "EventSubscription", "RunEvent", "utc_now"]
