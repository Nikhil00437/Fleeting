"""System endpoints: health, stats, SSE event stream."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

from .. import __version__
from ..events import sse_format
from ..models import BenchmarkIn
from ..services.preflight import Probe, check_all

router = APIRouter(prefix="/api", tags=["system"])


class SqlIn(BaseModel):
    """#295. `limit` is clamped again in the service; the default is for humans."""

    sql: str
    limit: int = 200

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


def _preflight_probe(st) -> "Probe":
    """Build the live probe. The note count is here rather than in the service
    because only the router holds a database handle — and it is wrapped by the
    caller, because the thing being checked is the sort of thing that throws."""
    return Probe(
        vault_dir=str(st.cfg.paths.vault_dir or ""),
        note_count=st.db.count_notes(),
        config=st.cfg,
    )


@router.get("/preflight")
def preflight(request: Request) -> dict:
    """#100: what is missing, and what to do about it.

    Not gated behind anything experimental. This is the first thing someone
    runs before anything is configured, so requiring a config change to see it
    would be the wrong order of operations.
    """
    st = request.app.state.st
    try:
        probe = _preflight_probe(st)
    except Exception as exc:  # noqa: BLE001 - a broken database is a *result*
        log.warning("preflight: could not read state", exc_info=True)
        probe = Probe(
            vault_dir=str(st.cfg.paths.vault_dir or ""), config=st.cfg
        )
        return {
            "ok": False,
            "checks": [
                {
                    "name": "vault",
                    "ok": False,
                    "required": True,
                    "detail": f"database unavailable: {exc}",
                    "fix": "check the database path and permissions, then restart",
                },
                *check_all(probe)["checks"],
            ],
        }
    return check_all(probe)


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
        # #195: a flag you cannot read is a flag you cannot remember you set.
        "experimental": {
            name: bool(getattr(st.cfg.experimental, name))
            for name in ("tone", "benchmark", "pinned_context")
        },
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


@router.post("/benchmark/run")
async def run_benchmark(body: BenchmarkIn, request: Request) -> dict:
    """#264 score candidate models on your own past notes.

    Read-only: nothing is written, and sensitive notes are excluded from the
    sample. Slow by nature — it is a handful of model calls per note — so the
    sample is small and the caller should not hold the tab open on 50 notes.
    """
    st = request.app.state.st
    from . import require_experimental  # #195

    require_experimental(st.cfg, "benchmark")

    from ..services.benchmark import benchmark_models

    if body.models and not [m for m in body.models if m.strip()]:
        raise HTTPException(422, "no model names given")
    return await benchmark_models(
        st.db, st.cfg, st.bus, models=body.models, sample=body.sample
    )


@router.get("/diagnostics")
async def diagnostics(request: Request, min_level: str = "WARNING", limit: int = 200) -> dict:
    """#395: everything a maintainer asks for, with secrets removed.

    Read-only. The bundle is redacted at the source rather than by the client,
    so there is no path where the unredacted config is serialised and only the
    UI decides what to drop — that ordering is what turns a display bug into a
    leak.

    `limit` is clamped here: it is a user-supplied query parameter and the
    bundle is meant to be pasted into a chat window.
    """
    st = request.app.state.st
    from ..config import DB_PATH, LOG_PATH
    from ..diagnostics import build_bundle

    return build_bundle(
        cfg=st.cfg,
        log_path=LOG_PATH,
        db_path=DB_PATH,
        min_level=min_level,
        limit=max(1, min(int(limit), 2000)),
    )


@router.get("/metrics/runtime")
async def runtime_metrics(request: Request, hours: int = 24) -> dict:
    """#390: jobs per hour, median enrichment time, error rate.

    Read-only. The window is clamped because `hours` arrives as a query
    parameter and the aggregation walks every note in it.
    """
    st = request.app.state.st
    from ..services.runtime_metrics import summarise

    return summarise(st.db, hours=max(1, min(int(hours), 24 * 30)))


@router.post("/sql")
async def run_sql(body: SqlIn, request: Request) -> dict:
    """#295: a read-only console over the app's own database.

    Gated behind `[experimental].sql_console` because it is the most powerful
    thing in the app. Read-only is enforced twice over — a separate `mode=ro`
    connection *and* an authorizer — because read-only mode does not stop
    ATTACH, and an attached database opens read-write. See
    `services/sqlite_console.py`; the tests there are mostly attempts to break
    it, because that is the only evidence that works.
    """
    st = request.app.state.st
    from . import require_experimental  # #195

    require_experimental(st.cfg, "sql_console")

    from ..config import DB_PATH
    from ..services.sqlite_console import QueryError, run_readonly

    try:
        return run_readonly(DB_PATH, body.sql, limit=body.limit)
    except QueryError as exc:
        # 400: the query was refused or would not run. Not 403 — the endpoint
        # exists, it is the query that is the problem, and the message is the
        # useful part.
        raise HTTPException(400, str(exc)) from exc
