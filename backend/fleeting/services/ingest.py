"""#119 and the ingest queue that #129/#130/#131/#132 share.

The bundle's own note is the design: *#132 is #130 with a different fetcher, so
one ingest queue.* Four sources, one set of things that have to be true of all of
them — resumable, idempotent, progress you can see, failures that say why — so
those live here once and each source is a parser behind `run_one`.

**Idempotence is the load-bearing property.** Re-running an import must not
duplicate a year of notes, so `ingested_sources` records what has been seen and a
second pass skips it. Every "import my notes folder again" is a thing people do
because they are not sure the first one worked, and an importer that duplicates
everything is worse than no importer.

**Imported notes go in as `status=pending`**, which is how every capture enters
the app. That is the whole mechanism behind "run through enrichment and
embeddings" — the import does not call the model, it joins the pipeline that
already does, and a folder of 2,000 notes queues instead of blocking.

**Imported digests are marked `generated`.** The app wrote them, the user did
not, and every text heuristic that reads a note — tone, clarity, the entity
index — is wrong on them, because LLM-written prose capitalises for sentences
rather than names. The flag exists so those heuristics can skip them.

**A failure is recorded, not raised.** One unreadable file in a folder of two
thousand should not abandon the other 1,999, and the job's error is how the user
finds out which one.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from ..db import new_id, now_iso

log = logging.getLogger("fleeting.ingest")

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

STATUSES = (PENDING, RUNNING, DONE, FAILED, SKIPPED)

# Ceilings per run. A folder of 2,000 files in one transaction is a long pause
# the user cannot interrupt, and a single unbounded job is a single point of
# failure for everything.
MAX_FILES_PER_RUN = 500


# ---- the queue -------------------------------------------------------------


def enqueue(db: Any, kind: str, source: str) -> dict[str, Any]:
    """Add one job. `source` is a path or a URL, depending on `kind`."""
    now = now_iso()
    job = {
        "id": new_id(),
        "kind": kind,
        "source": source,
        "status": PENDING,
        "note_id": None,
        "error": None,
        "detail": "{}",
        "created_at": now,
        "updated_at": now,
    }
    db.conn.execute(
        "INSERT INTO ingest_jobs (id, kind, source, status, note_id, error, detail, created_at, updated_at)"
        " VALUES (:id, :kind, :source, :status, :note_id, :error, :detail, :created_at, :updated_at)",
        job,
    )
    db.commit()
    return job


def _job(row: Any) -> dict[str, Any]:
    """A job with `detail` decoded.

    Decoded here so the shape is the same everywhere. A parser returns a `dict`
    for `detail` and `get_job` used to hand back the raw JSON *string*, which
    means every caller has to know which side of the boundary it is on — and the
    one that gets it wrong raises `TypeError: string indices must be integers`.
    That is the third time this session a result shape has varied by path.
    """
    job = dict(row)
    job["detail"] = _json_load(job.get("detail"))
    return job


def _json_load(raw: Any) -> dict[str, Any]:
    import json

    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def get_job(db: Any, job_id: str) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM ingest_jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row) if row else None


def list_jobs(db: Any, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Newest first. `limit` because this feeds a list a person reads, and an
    unbounded one turns itself into a database dump."""
    if status:
        rows = db.execute(
            # `rowid` breaks the tie: `created_at` is second-granular, so two
            # jobs queued in the same second were otherwise in arbitrary order.
            "SELECT * FROM ingest_jobs WHERE status = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM ingest_jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_job(r) for r in rows]


def _set(db: Any, job_id: str, **fields: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "id": job_id, "updated_at": now_iso()}
    db.conn.execute(f"UPDATE ingest_jobs SET {sets} WHERE id = :id", params)
    db.commit()


# ---- already-seen ----------------------------------------------------------


def already_ingested(db: Any, source: str, kind: str = "") -> bool:
    """Has this exact source been imported?

    Keyed on the resolved path/URL and the kind together: the same file imported
    as `markdown-folder` and as `rss` are different claims about it, and a
    half-finished job should be retryable rather than permanently skipped.
    """
    row = db.execute(
        "SELECT 1 FROM ingested_sources WHERE url = ? AND kind = ?", (source, kind)
    ).fetchone()
    return row is not None


def mark_ingested(db: Any, source: str, kind: str = "", title: str = "") -> None:
    db.conn.execute(
        "INSERT OR REPLACE INTO ingested_sources (url, kind, title, fetched_at) VALUES (?, ?, ?, ?)",
        (source, kind, title or None, now_iso()),
    )
    db.commit()


def forget_source(db: Any, source: str, kind: str = "") -> bool:
    """Allow a re-import. Without it, a partial import is unretryable forever."""
    cur = db.conn.execute(
        "DELETE FROM ingested_sources WHERE url = ? AND kind = ?", (source, kind)
    )
    db.commit()
    return bool(cur.rowcount)


# ---- progress --------------------------------------------------------------


def progress(db: Any) -> dict[str, Any]:
    """Counts by status. What a person looks at to answer "is it working?"."""
    counts = {status: 0 for status in STATUSES}
    for row in db.execute("SELECT status, COUNT(*) c FROM ingest_jobs GROUP BY status"):
        counts[row["status"]] = row["c"]
    total = sum(counts.values())
    finished = counts[DONE] + counts[FAILED] + counts[SKIPPED]
    return {
        "total": total,
        "counts": counts,
        "pending": counts[PENDING] + counts[RUNNING],
        # `progress` rather than `done/total`: a failed job is finished, and
        # reporting it as outstanding means the bar never reaches 100% on a
        # folder with one bad file in it.
        "progress": round(finished / total, 3) if total else 1.0,
        "finished": finished,
    }


def failures(db: Any, limit: int = 50) -> list[dict[str, Any]]:
    """What went wrong, with the reason. The error text is the only thing that
    tells a user which of two thousand files is unreadable."""
    return list_jobs(db, FAILED, limit=limit)


# ---- running ---------------------------------------------------------------


Parser = Callable[[Any, dict[str, Any], Any], dict[str, Any]]

# Registered per kind. Adding a source means adding a parser here, not another
# table and another runner.
PARSERS: dict[str, Parser] = {}


def register(kind: str) -> Callable[[Parser], Parser]:
    def wrap(fn: Parser) -> Parser:
        PARSERS[kind] = fn
        return fn

    return wrap


def run_one(db: Any, cfg: Any, job_id: str, bus: Any = None) -> dict[str, Any]:
    """Run one job. Never raises — a failure is recorded on the job.

    The distinction is deliberate: a job that raises leaves the row `running`
    forever, and there is no way to tell that from "still working" except by
    inspecting timestamps.
    """
    job = get_job(db, job_id)
    if not job:
        raise LookupError(f"job {job_id} not found")
    parser = PARSERS.get(job["kind"])
    if parser is None:
        _set(db, job_id, status=FAILED, error=f"no parser for kind {job['kind']!r}")
        return get_job(db, job_id) or {}

    _set(db, job_id, status=RUNNING)
    try:
        result = parser(db, cfg, job)
    except Exception as exc:  # noqa: BLE001
        log.warning("ingest job %s failed: %s", job_id, exc, exc_info=True)
        _set(db, job_id, status=FAILED, error=f"{type(exc).__name__}: {exc}")
        return get_job(db, job_id) or {}

    status = result.get("status", DONE)
    _set(
        db,
        job_id,
        status=status,
        note_id=result.get("note_id"),
        error=result.get("error"),
        detail=_json(result.get("detail") or {}),
    )
    if bus is not None:
        bus.publish("ingest.updated", {"id": job_id, "status": status})
    return get_job(db, job_id) or {}


def run_pending(db: Any, cfg: Any, limit: int = MAX_FILES_PER_RUN, bus: Any = None) -> list[dict[str, Any]]:
    """Drain up to `limit` pending jobs."""
    rows = db.execute(
        "SELECT id FROM ingest_jobs WHERE status = ? ORDER BY created_at ASC LIMIT ?",
        (PENDING, limit),
    ).fetchall()
    return [run_one(db, cfg, r["id"], bus) for r in rows]


def _json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


def _markdown_files(root: Path, limit: int = MAX_FILES_PER_RUN) -> list[Path]:
    """Markdown under `root`, bounded, skipping the usual noise folders."""
    skip = {".git", ".obsidian", "node_modules", ".trash", "__pycache__"}
    out: list[Path] = []
    stack = [(root, 0)]
    while stack and len(out) < limit:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if len(out) >= limit:
                break
            if entry.is_dir():
                if entry.name in skip or depth >= 8:
                    continue
                stack.append((entry, depth + 1))
            elif entry.suffix.lower() in (".md", ".markdown"):
                out.append(entry)
    return sorted(out)