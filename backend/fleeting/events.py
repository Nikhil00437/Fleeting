"""In-process event bus for live UI updates (SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

log = logging.getLogger("fleeting.events")


class EventBus:
    """Fan-out of JSON events to SSE subscribers and in-process callbacks."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._handlers: dict[str, list[Callable[[Any], None]]] = {}

    def subscribe(
        self,
        event_type: str | None = None,
        handler: Callable[[Any], None] | None = None,
    ) -> asyncio.Queue | None:
        if event_type is not None and handler is not None:
            self._handlers.setdefault(event_type, []).append(handler)
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(
        self,
        target: Any,
        event_type: str | None = None,
    ) -> None:
        if isinstance(target, asyncio.Queue):
            self._subscribers.discard(target)
        elif event_type and event_type in self._handlers:
            if target in self._handlers[event_type]:
                self._handlers[event_type].remove(target)

    def publish(self, event_type: str, data: Any) -> None:
        payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False, default=str)
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("event subscriber queue full — dropping event")
        for handler in self._handlers.get(event_type, []):
            try:
                handler(data)
            except Exception:
                log.exception("event handler for %s failed", event_type)


def sse_format(payload: str) -> str:
    return f"data: {payload}\n\n"
