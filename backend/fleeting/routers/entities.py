"""#411 people index endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import NoteOut
from ..services.entities import notes_for_person, people_index

router = APIRouter(prefix="/api/entities", tags=["entities"])


@router.get("/people")
def people(request: Request) -> list[dict]:
    """#411 the index, #412 each entry carrying when they were last mentioned.

    #416 ("who have I not talked to in a while") is the same list filtered on
    # `last_seen` — no second query, and no way for the two to disagree.
    """
    return people_index(request.app.state.st.db)


@router.get("/people/{name}/notes")
def person_notes(name: str, request: Request) -> list[NoteOut]:
    """#413 every note mentioning this person, newest first."""
    st = request.app.state.st
    if not any(p["name"].lower() == name.lower() for p in people_index(st.db)):
        raise HTTPException(404, "person not found in notes")
    return [NoteOut(**n) for n in notes_for_person(st.db, name)]
