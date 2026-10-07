"""Search, tags, tasks, stats."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

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
    # #315: hybrid RRF keyword weight — 1.0 = pure FTS5, 0.0 = pure vector.
    alpha: float = Query(0.5, ge=0.0, le=1.0),
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
        alpha=alpha,
        filter_type=type,
        repo=repo,
    )
    # #322/#49: every real search feeds the log (capped server-side).
    st.db.record_query(q, len(results))
    return [NoteOut(**r) for r in results]


@router.get("/search/log")
def search_log(request: Request, limit: int = Query(10, ge=1, le=100), sort: str = "recent") -> list[dict]:
    """#49 recent searches / #322 most searched. sort=recent|top."""
    return request.app.state.st.db.query_log(limit=limit, sort=sort)


@router.get("/search/history")
def search_history(request: Request) -> dict:
    """Both flavours the UI wants in one round trip: recent + most searched."""
    db = request.app.state.st.db
    return {
        "recent": db.query_log(limit=8, sort="recent"),
        "top": db.query_log(limit=5, sort="top"),
    }


class SearchFeedbackIn(BaseModel):
    note_id: str
    query: str = Field(min_length=1, max_length=500)
    down: bool = True


@router.post("/search/feedback")
def search_feedback(body: SearchFeedbackIn, request: Request) -> dict:
    """#321 'not relevant' — demotes the note for this query. Send
    down=false to undo (removes the mark)."""
    st = request.app.state.st
    if not st.db.get_note(body.note_id):
        raise HTTPException(404, "note not found")
    if body.down:
        st.db.add_search_feedback(body.note_id, body.query)
    else:
        st.db.remove_search_feedback(body.note_id, body.query)
    return {"ok": True, "note_id": body.note_id, "down": body.down}


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



@router.get("/search/unified")
async def unified(
    request: Request,
    q: str,
    limit: int = Query(20, ge=1, le=200),
    since_day: str | None = None,
) -> dict:
    """Search notes, window sessions and commits together.

    Separate from `/search` on purpose: that endpoint returns a bare array of
    notes and the existing UI depends on its shape.
    """
    from ..services.search import unified_search

    st = request.app.state.st
    return await unified_search(st.db, st.cfg, q, limit=limit, since_day=since_day)
