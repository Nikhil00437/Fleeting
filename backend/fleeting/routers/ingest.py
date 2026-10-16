"""Ingest endpoints: queue a source, preview it, run it, watch progress.

One queue rather than a table per source — the bundle's own note is that #132 is
#130 with a different fetcher, so the status, error, re-run and progress
behaviour is worth having once.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class EnqueueIn(BaseModel):
    kind: str
    source: str


class PreviewIn(EnqueueIn):
    pass


@router.get("/jobs")
def ingest_jobs(request: Request, status: str | None = None) -> dict:
    from ..services.ingest import list_jobs

    return {"jobs": list_jobs(request.app.state.st.db, status)}


@router.get("/progress")
def ingest_progress(request: Request) -> dict:
    from ..services.ingest import progress

    return progress(request.app.state.st.db)


@router.get("/failures")
def ingest_failures(request: Request) -> dict:
    """What went wrong and why. The error text is the only thing that tells a
    user which of two thousand files is unreadable."""
    from ..services.ingest import failures

    return {"failures": failures(request.app.state.st.db)}


@router.post("")
def enqueue_ingest(body: EnqueueIn, request: Request) -> dict:
    from ..services.ingest import enqueue

    return enqueue(request.app.state.st.db, body.kind, body.source)


@router.post("/preview")
def preview_ingest(body: PreviewIn, request: Request) -> dict:
    """What this import would do, without doing it. The button is one click from
    two thousand notes."""
    from ..services import ingest_markdown

    if body.kind != ingest_markdown.KIND:
        raise HTTPException(
            400,
            {"error": "unsupported_kind", "kind": body.kind, "supported": [ingest_markdown.KIND]},
        )
    st = request.app.state.st
    return ingest_markdown.preview(st.db, st.cfg.paths, body.source)


@router.post("/jobs/{job_id}/run")
def run_ingest_job(job_id: str, request: Request) -> dict:
    from ..services.ingest import run_one

    st = request.app.state.st
    try:
        return run_one(st.db, st.cfg, job_id, bus=getattr(st, "bus", None))
    except LookupError as exc:
        raise HTTPException(404, {"error": "no_such_job", "id": job_id}) from exc
