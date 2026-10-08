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


@router.get("/search/transcript")
def transcript_search_endpoint(
    request: Request,
    q: str,
    limit: int = Query(10, ge=1, le=50),
    hits_per_note: int = Query(5, ge=1, le=20),
) -> list[dict]:
    """#319: voice-note transcripts with word-timestamp hits — the UI jumps
    the audio player to `t`."""
    from ..services.transcript_search import transcript_search

    st = request.app.state.st
    if not q.strip():
        return []
    return transcript_search(st.db, q, limit=limit, hits_per_note=hits_per_note)


@router.get("/recall")
def recall(
    request: Request,
    kind: str = Query("random", pattern="^(random|this_day|capsule)$"),
    older_than_days: int = Query(90, ge=1, le=3650),
    seed: int | None = None,
    limit: int = Query(5, ge=1, le=20),
) -> list[NoteOut]:
    """#46 random old note, #47 this day last year, #297 weekly time capsule."""
    from ..services.recall import recall_random_old, recall_this_day, recall_time_capsule

    db = request.app.state.st.db
    if kind == "this_day":
        hits = recall_this_day(db, limit=limit)
    elif kind == "capsule":
        capsule = recall_time_capsule(db)
        hits = [capsule] if capsule else []
    else:
        hits = recall_random_old(db, older_than_days=older_than_days, limit=limit, seed=seed)
    return [NoteOut(**h) for h in hits]


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


class TagRenameIn(BaseModel):
    from_tag: str = Field(min_length=1, max_length=120)
    to: str = Field(min_length=1, max_length=120)


@router.post("/tags/rename")
def rename_tag(body: TagRenameIn, request: Request) -> dict:
    """#50: rewrite one tag across notes. Emits note.updated per changed
    note so every open view stays live."""
    st = request.app.state.st
    updated = st.db.rename_tag(body.from_tag, body.to)
    for note in updated:
        st.bus.publish("note.updated", note)
    return {"ok": True, "updated": len(updated)}


class TagMergeIn(BaseModel):
    from_tags: list[str] = Field(min_length=1, max_length=20)
    to: str = Field(min_length=1, max_length=120)


@router.post("/tags/merge")
def merge_tags(body: TagMergeIn, request: Request) -> dict:
    """#50/#425: fold several tags into one."""
    st = request.app.state.st
    updated = st.db.merge_tags(body.from_tags, body.to)
    for note in updated:
        st.bus.publish("note.updated", note)
    return {"ok": True, "updated": len(updated)}


class TagDeleteIn(BaseModel):
    tag: str = Field(min_length=1, max_length=120)


@router.post("/tags/delete")
def delete_tag(body: TagDeleteIn, request: Request) -> dict:
    """#50: strip a tag from every note (notes themselves stay)."""
    st = request.app.state.st
    updated = st.db.delete_tag(body.tag)
    for note in updated:
        st.bus.publish("note.updated", note)
    return {"ok": True, "updated": len(updated)}


@router.get("/tags/audit")
def tags_audit(request: Request) -> dict:
    """#425: rare, overlapping and misspelt tag candidates."""
    from ..services.tag_audit import tag_audit

    return tag_audit(request.app.state.st.db)


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
