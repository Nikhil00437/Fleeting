"""Collections router — #267 projects, #268 manual playlists, #269 saved queries.

One resource with a `kind` (the bundle's cut/merge decision): one CRUD, one
UI section. Saved queries re-execute on every read, so a collection defined
by a filter keeps collecting without anyone touching it.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..models import NoteOut

router = APIRouter(prefix="/api/collections", tags=["collections"])

log = logging.getLogger("fleeting.collections")


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="manual", pattern="^(manual|saved_query|project)$")
    description: str = Field(default="", max_length=2000)
    status: str | None = Field(default=None, max_length=32)
    # saved_query payload: {text?, tag?, type?, starred?}
    query: dict | None = None


class CollectionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, max_length=32)
    query: dict | None = None


class CollectionAddNoteIn(BaseModel):
    note_id: str


def _out(coll: dict) -> dict:
    return coll


@router.get("")
def list_collections(request: Request) -> list[dict]:
    st = request.app.state.st
    return [_out(c) for c in st.db.list_collections()]


@router.post("")
def create_collection(body: CollectionIn, request: Request) -> dict:
    st = request.app.state.st
    coll = st.db.insert_collection(body.model_dump())
    st.bus.publish("collections.changed", {"id": coll["id"], "action": "created"})
    return _out(coll)


@router.get("/{coll_id}")
def get_collection(coll_id: str, request: Request) -> dict:
    st = request.app.state.st
    coll = st.db.get_collection(coll_id)
    if not coll:
        raise HTTPException(404, "collection not found")
    notes = st.db.collection_notes(coll)
    return {**coll, "notes": [NoteOut(**n) for n in notes]}


@router.patch("/{coll_id}")
def update_collection(coll_id: str, body: CollectionUpdateIn, request: Request) -> dict:
    st = request.app.state.st
    coll = st.db.update_collection(coll_id, body.model_dump(exclude_unset=True))
    if not coll:
        raise HTTPException(404, "collection not found")
    st.bus.publish("collections.changed", {"id": coll_id, "action": "updated"})
    return _out(coll)


@router.delete("/{coll_id}")
def delete_collection(coll_id: str, request: Request) -> dict:
    st = request.app.state.st
    if not st.db.delete_collection(coll_id):
        raise HTTPException(404, "collection not found")
    st.bus.publish("collections.changed", {"id": coll_id, "action": "deleted"})
    return {"ok": True, "id": coll_id}


@router.post("/{coll_id}/notes")
def add_note(coll_id: str, body: CollectionAddNoteIn, request: Request) -> dict:
    st = request.app.state.st
    if not st.db.add_note_to_collection(coll_id, body.note_id):
        raise HTTPException(404, "collection or note not found")
    st.bus.publish("collections.changed", {"id": coll_id, "action": "updated"})
    return {"ok": True}


@router.delete("/{coll_id}/notes/{note_id}")
def remove_note(coll_id: str, note_id: str, request: Request) -> dict:
    st = request.app.state.st
    if not st.db.remove_note_from_collection(coll_id, note_id):
        raise HTTPException(404, "note not in collection")
    st.bus.publish("collections.changed", {"id": coll_id, "action": "updated"})
    return {"ok": True}
