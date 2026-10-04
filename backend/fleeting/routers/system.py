"""System endpoints: health, stats, SSE event stream."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..events import sse_format

router = APIRouter(prefix="/api", tags=["system"])

log = logging.getLogger("fleeting.system")


def _embedding_status(st) -> tuple[str, int]:
    """Which embedding model is in use, and how many notes still need migrating.

    Mirrors the branch in `embed_text_with_model`: anything but a working
    remote provider means the offline hash vectorizer, which is a lexical
    signal rather than a semantic one.
    """
    llm = st.cfg.llm
    if llm.provider == "none":
        return "local-hash-384", 0
    model = llm.model or (
        "nomic-embed-text" if llm.provider == "ollama" else "text-embedding-3-small"
    )
    try:
        stale = st.db.count_stale_embeddings(model)
    except Exception:
        log.warning("could not count stale embeddings", exc_info=True)
        stale = 0
    return model, stale


@router.get("/health")
def health(request: Request) -> dict:
    st = request.app.state.st
    queue = 0
    try:
        st.db.count_notes()
        db_ok = True
        queue = st.db.count_notes("pending") + st.db.count_notes("processing")
    except Exception:
        log.error("health: database probe failed", exc_info=True)
        db_ok = False

    embedding_model, stale = ("local-hash-384", 0) if not db_ok else _embedding_status(st)
    semantic = embedding_model != "local-hash-384"

    degradations: list[str] = []
    if not db_ok:
        degradations.append("Database is unreachable — notes cannot be read or saved.")
    if st.cfg.llm.provider == "none":
        degradations.append(
            "No LLM configured — notes use heuristic titles and summaries instead of the model."
        )
    elif st.cfg.llm.provider != "none" and not semantic:
        degradations.append("Embeddings are offline-only — semantic search is lexical.")
    if stale:
        degradations.append(
            f"{stale} note(s) still use the old embedding model and will not match "
            f"semantic searches until they are re-embedded."
        )

    return {
        "ok": db_ok,
        "version": __version__,
        "uptime_secs": int(time.time() - st.started_at) if st.started_at else 0,
        "db": db_ok,
        "whisper_loaded": st.transcriber.is_ready(),
        "queue": queue,
        "embedding_model": embedding_model,
        "semantic_search": "semantic" if semantic else "lexical",
        "stale_embeddings": stale,
        "degradations": degradations,
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
