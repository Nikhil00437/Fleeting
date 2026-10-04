"""Search, tags, tasks, stats."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..models import NoteOut
from ..services.semantic_search import hybrid_search

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    request: Request,
    q: str,
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    mode: str = "hybrid",
    type: str | None = None,
    repo: str | None = None,
) -> list[NoteOut]:
    st = request.app.state.st
    if not q.strip():
        return []
    results = hybrid_search(
        st.db,
        q,
        st.cfg,
        mode=mode,
        limit=limit,
        filter_type=type,
        repo=repo,
    )
    return [NoteOut(**r) for r in results]


@router.get("/tags")
def tags(request: Request) -> list[dict]:
    return request.app.state.st.db.all_tags()


@router.get("/stats")
def stats(request: Request, days: int = 7) -> dict:
    st = request.app.state.st
    data = st.db.stats()
    data["queue"] = st.db.count_notes("pending") + st.db.count_notes("processing")
    data["notes_per_day"] = st.db.notes_per_day(min(max(days, 2), 60))
    return data

