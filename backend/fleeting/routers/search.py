"""Search, tags, tasks, stats."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import NoteOut

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(request: Request, q: str, limit: int = 50) -> list[NoteOut]:
    st = request.app.state.st
    if not q.strip():
        return []
    results = st.db.search(q, limit=min(limit, 200))
    return [NoteOut(**r) for r in results]


@router.get("/tags")
def tags(request: Request) -> list[dict]:
    return request.app.state.st.db.all_tags()


@router.get("/tasks")
def tasks(request: Request, include_done: bool = False) -> list[dict]:
    return request.app.state.st.db.open_tasks(include_done=include_done)


@router.get("/stats")
def stats(request: Request, days: int = 7) -> dict:
    st = request.app.state.st
    data = st.db.stats()
    data["queue"] = st.db.count_notes("pending") + st.db.count_notes("processing")
    data["notes_per_day"] = st.db.notes_per_day(min(max(days, 2), 60))
    return data

