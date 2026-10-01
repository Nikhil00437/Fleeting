"""System endpoints: health, stats, SSE event stream."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..events import sse_format

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(request: Request) -> dict:
    st = request.app.state.st
    try:
        st.db.count_notes()
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "version": __version__,
        "uptime_secs": int(time.time() - st.started_at) if st.started_at else 0,
        "db": db_ok,
        "whisper_loaded": st.transcriber.is_ready(),
        "queue": st.db.count_notes("pending") + st.db.count_notes("processing"),
    }


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    queue = request.app.state.st.bus.subscribe()

    async def stream():
        try:
            yield sse_format('{"type": "hello", "data": {}}')
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                    yield sse_format(payload)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            request.app.state.st.bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
