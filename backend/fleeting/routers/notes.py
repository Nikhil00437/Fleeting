"""Notes CRUD router."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import save_config
from ..db import now_iso
from ..models import NoteOut, NoteUpdateIn
from ..services import markdown
from ..services.embeddings import embed_note

router = APIRouter(prefix="/api/notes", tags=["notes"])

log = logging.getLogger("fleeting.notes")


def _out(note: dict) -> NoteOut:
    return NoteOut(**note)


@router.get("")
def list_notes(
    request: Request,
    # ge=1 matters: SQLite treats a negative LIMIT as "no limit", so an
    # unclamped limit=-1 would stream the whole table (full transcripts).
    limit: int = Query(100, ge=1, le=500, description="Max notes to return"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    tag: str | None = None,
    status: str | None = None,
    type: str | None = None,
    archived: bool = False,
) -> list[NoteOut]:
    st = request.app.state.st
    notes = st.db.list_notes(
        limit=limit,
        offset=offset,
        tag=tag,
        status=status,
        note_type=type,
        archived=archived,
    )
    return [_out(n) for n in notes]


@router.get("/{note_id}")
def get_note(note_id: str, request: Request) -> NoteOut:
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    return _out(note)


@router.patch("/{note_id}")
def update_note(note_id: str, body: NoteUpdateIn, request: Request) -> NoteOut:
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        return _out(note)

    # title edits also refresh the vault mirror
    note = st.db.update_note(note_id, changes)
    assert note is not None
    if note["status"] == "done":
        markdown.sync_note(st.cfg.paths, note)

    # Re-embed: semantic search reads note_embeddings, which no update path
    # touched, so an edited note stayed findable only by its old text.
    searchable = {"title", "summary", "raw_text", "tags"} & set(changes)
    if searchable:
        try:
            embed_note(note, st.db, st.cfg)
        except Exception:
            # Never fail the user's edit over a best-effort index update.
            log.warning("re-embed failed for note %s", note_id, exc_info=True)

    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/pin")
def toggle_pin(note_id: str, request: Request) -> NoteOut:
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"pinned": not note["pinned"]})
    assert note
    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/archive")
def toggle_archive(note_id: str, request: Request) -> NoteOut:
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"archived": not note["archived"]})
    assert note
    st.bus.publish("note.updated", note)
    return _out(note)


@router.delete("/{note_id}")
def delete_note(note_id: str, request: Request) -> dict:
    st = request.app.state.st
    note = st.db.delete_note(note_id, audio_root=st.cfg_audio_dir())
    if not note:
        raise HTTPException(404, "note not found")
    markdown.remove_note(st.cfg.paths, note)
    st.bus.publish("note.deleted", {"id": note_id})
    return {"ok": True, "id": note_id}


@router.post("/{note_id}/reprocess")
async def reprocess_note(note_id: str, request: Request) -> NoteOut:
    """Re-run the full pipeline (transcribe + enrich) for a note."""
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    st.db.update_note(
        note_id,
        {"status": "pending", "error": None, "processed_at": None},
    )
    st.processor.enqueue(note_id)
    note = st.db.get_note(note_id)
    assert note
    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/export")
def export_note(note_id: str, request: Request) -> dict:
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    path = markdown.sync_note(st.cfg.paths, note)
    if path is None:
        raise HTTPException(400, "vault sync is disabled in settings")
    return {"ok": True, "path": str(path)}
