"""#94 health panel inputs.

Nearly everything here was already computed and discarded — llm_traces holds
the duration of every call, the processor knows its queue depth, and the
embedding path logs a downgrade the user never sees. This module is the
surface that makes those legible, and it refuses to invent a number it does
not have: no calls means `avg_ms is None`, not 0, because "0ms" reads as
"instantly fast" and that is a different claim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database

RECENT_LIMIT = 20

# The offline vectorizer is not a degraded *mode* — it is a different thing
# entirely, and the panel has to say so rather than implying the index is
# quietly fine.
DEGRADED_MODEL = "local-hash-384"


def llm_health(db: Database, *, kind: str = "chat", limit: int = RECENT_LIMIT) -> dict:
    """Latency and failure rate over the most recent calls of one kind."""
    traces = db.list_llm_traces(kind=kind, limit=limit)
    if not traces:
        return {"calls": 0, "avg_ms": None, "max_ms": None, "errors": 0, "last_error": None}

    durations = [int(t.get("ms") or 0) for t in traces]
    failed = [t for t in traces if t.get("error")]
    last_error = failed[0]["error"] if failed else None
    return {
        "calls": len(traces),
        "avg_ms": sum(durations) // len(durations),
        "max_ms": max(durations),
        "errors": len(failed),
        "last_error": last_error,
    }


def embedding_status(db: Database, last_model: str | None) -> dict:
    """Is semantic search real, or lexical in disguise?

    `last_model` is the model the last successful embed reported. The offline
    vectorizer silently downgrades every semantic search to keyword matching,
    and the user has no other way to find that out.
    """
    row = db.execute("SELECT dimensions FROM note_embeddings LIMIT 1").fetchone()
    degraded = last_model == DEGRADED_MODEL
    return {
        "model": last_model,
        "degraded": degraded,
        "dimensions": int(row["dimensions"]) if row else 0,
        "indexed": 0 if row is None else int(
            db.execute("SELECT COUNT(*) AS n FROM note_embeddings").fetchone()["n"]
        ),
        "detail": (
            "The offline hash vectorizer is in use — semantic search is "
            "lexical-only until the embedding provider is reachable."
            if degraded
            else ""
        ),
    }


def queue_status(processor: object | None) -> dict:
    """Depth and in-flight count for the capture pipeline."""
    from ..process import Processor

    if processor is None:
        return {"depth": 0, "max": Processor.QUEUE_MAX, "inflight": 0, "running": False}
    return {
        "depth": getattr(processor.queue, "qsize", lambda: 0)(),
        "max": Processor.QUEUE_MAX,
        "inflight": len(getattr(processor, "_inflight", ()) or ()),
        "running": bool(getattr(processor, "_worker_tasks", ())),
    }
