"""System endpoints: health, stats, SSE event stream."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

from .. import __version__
from ..events import sse_format
from ..models import BenchmarkIn
from ..main import _db_path
from ..services.offline import report
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


@router.get("/audit")
def audit_log(request: Request, limit: int = 50, action: str | None = None) -> dict:
    """#140: what changed and what was destroyed, newest first.

    Read-only by construction — an audit log you can write through is not one.
    """
    return {"entries": request.app.state.st.db.audit_log(limit=limit, action=action)}


@router.get("/backups")
def backups_endpoint(request: Request) -> dict:
    """#457: what backups exist, and whether the index still describes them.

    Read-only on purpose. Restoring a backup is a separate, deliberate act, and
    an endpoint that both lists and restores invites a UI button one click away
    from the wrong file.
    """
    from ..services.backup_index import read_all, verify
    from ..db import _backup_index_path

    index = _backup_index_path(_db_path())
    return {
        "backups": read_all(index),
        "problems": verify(index),
    }


@router.get("/encryption")
def encryption_status() -> dict:
    """#99: what content encryption covers, and what it does not.

    Ungated. The honest answer — including the part that is *not* encrypted — is
    the reason to expose it.
    """
    from ..services.crypto import status as _status

    return _status()


class BackupIn(BaseModel):
    """#97. The passphrase is per-call and never stored — that is what lets a
    backup restore on a machine that has never seen this keyring."""

    passphrase: str


class RestoreIn(BackupIn):
    confirm: bool = False


def _backups_dir() -> Path:
    return Path(_db_path()).parent / "backups"


@router.post("/backups")
def create_backup(request: Request, body: BackupIn) -> dict:
    """Write an encrypted backup and record it in the hash-chained index."""
    from ..db import _backup_index_path
    from ..services.backup_crypto import BackupError, create
    from ..services.backup_index import append as _append_index

    if not body.passphrase:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "passphrase_required",
                "message": "A backup is encrypted with this passphrase. Without one "
                "the file would be readable by anyone who gets hold of it.",
            },
        )
    out = _backups_dir() / f"fleeting-{int(time.time())}.backup"
    try:
        entry = create(_db_path(), out, body.passphrase)
    except BackupError as exc:
        raise HTTPException(status_code=400, detail={"error": "backup_failed", "message": str(exc)}) from exc
    try:
        # `append` hashes the file itself; passing a hash in is not its signature.
        _append_index(_backup_index_path(_db_path()), out, kind="encrypted")
    except Exception:  # noqa: BLE001
        log.warning("could not index %s", out.name, exc_info=True)
    return entry


@router.post("/backups/{name}/restore")
def restore_backup(request: Request, name: str, body: RestoreIn) -> dict:
    """Replace the live database with a backup. Wholesale, not a merge.

    Guarded by the same confirmation every other bulk destructive call uses,
    because the original is gone the moment this succeeds — and there is no
    "undo" that is not another restore.
    """
    from ..services.backup_crypto import BackupError, restore
    from ..services.bulk import preview, require_confirm

    path = (_backups_dir() / name).resolve()
    # `name` comes from the URL, so it is not trusted to stay inside our own
    # directory. Resolving and checking containment is what stops `../../` from
    # turning a restore into an arbitrary file write.
    if not path.is_relative_to(_backups_dir().resolve()) or not path.exists():
        raise HTTPException(status_code=404, detail={"error": "no_such_backup", "file": name})
    require_confirm(body, body.confirm, preview(1, [name], operation="restore over the live database"))
    try:
        return restore(path, _db_path(), body.passphrase)
    except BackupError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "restore_failed", "message": str(exc)}
        ) from exc


@router.get("/keyring")
def keyring_status() -> dict:
    """#139: where secrets are stored, and whether that store is a real one.

    Ungated and secret-free by construction: it reports the backend *name* and
    whether it is secure, never a value.
    """
    from ..services.keyring import status as _keyring_status

    return _keyring_status()


@router.get("/inventory")
def inventory_endpoint(request: Request) -> dict:
    """#137: what is stored per category, and how big.

    Ungated, like `/api/offline`. It is the answer to "how much of this do I
    actually have", and that question should not require a config change to ask.
    """
    from ..services.inventory import inventory

    return inventory(request.app.state.st.db, request.app.state.st.cfg)


@router.get("/offline")
def offline_status(request: Request) -> dict:
    """#460: what this machine would reach for, and whether it leaves.

    Deliberately ungated and cheap — it is the answer to "does this thing phone
    home?", and that question should not require a config change to ask.
    """
    return report(request.app.state.st.cfg)


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
