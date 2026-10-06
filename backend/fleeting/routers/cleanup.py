"""Cleanup assistant endpoints (#421): suggestions + explicit apply."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import cleanup

router = APIRouter(prefix="/api/cleanup", tags=["cleanup"])


class CleanupApplyIn(BaseModel):
    note_id: str
    action: str = Field(pattern="^(archive|add_tag)$")
    value: str | None = Field(default=None, max_length=120)


@router.get("")
def suggestions(request: Request) -> list[dict]:
    return cleanup.cleanup_suggestions(request.app.state.st.db)


@router.post("/apply")
def apply(request: Request, body: CleanupApplyIn) -> dict:
    """Apply one suggestion. Suggestions are proposals — nothing mutates here
    without this explicit call (the UI buttons hit it)."""
    st = request.app.state.st
    note = st.db.get_note(body.note_id)
    if not note:
        raise HTTPException(404, "note not found")

    if body.action == "archive":
        updated = st.db.update_note(body.note_id, {"archived": True})
        reason = "archived via cleanup"
    else:
        if not body.value:
            raise HTTPException(422, "add_tag needs a value")
        tags = list(note["tags"] or [])
        if body.value not in tags:
            tags.append(body.value)
        updated = st.db.update_note(body.note_id, {"tags": tags})
        reason = f"tagged #{body.value} via cleanup"

    assert updated
    st.bus.publish("note.updated", updated)
    return {"ok": True, "note_id": body.note_id, "reason": reason}
