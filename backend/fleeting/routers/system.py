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

    Delegates the name to `resolve_embedding_model` — this used to mirror the
    branch inside `embed_text_with_model`, and the two disagreed, which made
    every row count as stale and re-triggered the boot-time backfill forever.
    """
    from ..services.embedding_model import resolve_embedding_model

    llm = st.cfg.llm
    if llm.provider == "none":
        return "local-hash-384", 0
    model = resolve_embedding_model(llm)
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


SAMPLE_NOTES = [
    {
        "type": "text",
        "title": "Welcome to Fleeting",
        "summary": "Everything you capture lands here. This note is yours to trash.",
        "raw_text": (
            "Captures arrive unsorted and get enriched automatically: a title, "
            "a summary and tags. Try selecting this card and pressing Delete — "
            "it goes to the trash, not into the void."
        ),
        "tags": ["welcome"],
    },
    {
        "type": "text",
        "title": "Wikilinks connect thoughts",
        "summary": "Type [[Welcome to Fleeting]] inside any note to link it.",
        "raw_text": (
            "This note links to [[Welcome to Fleeting]]. Open the other note "
            "and check its backlinks. Links resolve by title and keep working "
            "when notes are renamed."
        ),
        "tags": ["welcome", "howto"],
    },
    {
        "type": "voice",
        "title": "Voice memos transcribe themselves",
        "summary": "Captured audio is transcribed, timestamped and enriched locally.",
        "raw_text": (
            "If you had recorded this, whisper would have turned your speech "
            "into this text — then cleaned it up, added tags and extracted "
            "action items. Click a card's pencil icon to edit inline."
        ),
        "tags": ["welcome", "voice"],
    },
    {
        "type": "text",
        "title": "Mark private things as sensitive",
        "summary": "Sensitive notes never leave the database: no vault mirror, no LLM, no embeddings.",
        "raw_text": (
            "Open the shield icon in a note's drawer to toggle sensitivity. "
            "Also worth knowing: the zzz button snoozes a note until tomorrow "
            "or next Monday, and the star keeps important notes easy to find."
        ),
        "tags": ["welcome", "privacy"],
    },
]


@router.get("/orphans")
def orphans(request: Request, limit: int = 50) -> dict:
    """#422: single-use tags, untagged notes and unlinked tasks."""
    return request.app.state.st.db.orphans(limit=max(1, min(limit, 500)))


@router.post("/samples")
def create_samples(request: Request) -> dict:
    """#488: fill an empty vault with deletable sample notes.

    Idempotent-ish by design: only runs when the vault holds no real notes,
    so a stray double-click cannot litter a working inbox.
    """
    st = request.app.state.st
    if st.db.count_notes() > 0:
        return {"ok": False, "created": 0, "reason": "vault not empty"}
    created = []
    for sample in SAMPLE_NOTES:
        note = st.db.insert_note({**sample, "status": "done"})
        st.bus.publish("note.created", note)
        created.append(note["id"])
    return {"ok": True, "created": len(created)}
