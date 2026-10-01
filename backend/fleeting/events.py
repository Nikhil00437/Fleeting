"""In-process event bus for live UI updates (SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger("fleeting.events")


class EventBus:
    """Fan-out of JSON events to any number of SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event_type: str, data: Any) -> None:
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("event subscriber queue full — dropping event")


def sse_format(payload: str) -> str:
    return f"data: {payload}\n\n"
