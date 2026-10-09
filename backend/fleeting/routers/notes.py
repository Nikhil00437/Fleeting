"""Notes CRUD router."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..config import save_config
from ..db import now_iso
from ..events import EventBus
from ..models import NoteOut, NoteUpdateIn, RegenerateIn, SnoozeIn
from ..services import markdown
from ..services.embeddings import embed_note
from ..services.fewshot import build_few_shot

router = APIRouter(prefix="/api/notes", tags=["notes"])

log = logging.getLogger("fleeting.notes")


def _bus(request: Request) -> EventBus:
    return getattr(request.app.state.st, "bus", None) or EventBus()


def _out(note: dict) -> NoteOut:
    return NoteOut(**note)


def _resolve_snooze(until: str | None) -> str | None:
    """Snooze preset or date -> a UTC ISO wake-up stamp. None wakes the note now.

    Presets land on human hours (18:00 / 08:00 local), not "now + N", because
    "tomorrow" that fires at 3am is not what anyone means.
    """
    if not until or not until.strip():
        return None
    u = until.strip().lower()
    now = datetime.now().astimezone()
    if u in ("later", "later_today", "this_evening", "evening"):
        wake = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if wake <= now:
            wake += timedelta(days=1)
    elif u == "tomorrow":
        wake = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    elif u in ("next_monday", "next_week", "nextweek"):
        wake = (now + timedelta(days=(7 - now.weekday()) % 7 or 7)).replace(
            hour=8, minute=0, second=0, microsecond=0
        )
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", u):
        try:
            wake = datetime.strptime(u, "%Y-%m-%d").replace(hour=8)
        except ValueError as exc:
            raise HTTPException(422, "not a real date") from exc
    else:
        try:
            wake = datetime.fromisoformat(until.strip())
        except ValueError as exc:
            raise HTTPException(
                422,
                "until must be 'later', 'tomorrow', 'next_monday', YYYY-MM-DD, or an ISO timestamp",
            ) from exc
    return wake.astimezone(timezone.utc).isoformat(timespec="seconds")


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
    starred: bool = False,
    review_state: str | None = None,
) -> list[NoteOut]:
    st = request.app.state.st
    notes = st.db.list_notes(
        limit=limit,
        offset=offset,
        tag=tag,
        status=status,
        note_type=type,
        archived=archived,
        starred=starred,
        review_state=review_state,
    )
    return [_out(n) for n in notes]


# Literal paths must register before /{note_id}, or FastAPI hands "snoozed"
# to the id route and 404s.
@router.get("/snoozed")
def list_snoozed(request: Request) -> list[NoteOut]:
    """#14: what is currently hidden by a snooze, in wake-up order."""
    st = request.app.state.st
    return [_out(n) for n in st.db.snoozed_notes()]


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
    # Empty colour string means "clear" (see NoteUpdateIn); None is "leave alone".
    if changes.get("color") == "":
        changes["color"] = None
    if not changes:
        return _out(note)

    # title edits also refresh the vault mirror
    old_raw = note.get("raw_text") or ""
    note = st.db.update_note(note_id, changes)
    assert note is not None
    if note["status"] == "done":
        markdown.sync_note(st.cfg.paths, note)

    # #435: a human fixing a voice transcript teaches whisper new words.
    if note["type"] == "voice" and "raw_text" in changes:
        from ..services.transcribe import added_words

        new = added_words(old_raw, note.get("raw_text") or "")
        if new:
            existing = {w.strip() for w in st.cfg.transcribe.vocabulary.split(",") if w.strip()}
            extra = [w for w in new if w not in existing]
            if extra:
                st.cfg.transcribe.vocabulary = ", ".join(
                    [v.strip() for v in st.cfg.transcribe.vocabulary.split(",") if v.strip()] + extra
                )
                save_config(st.cfg)

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


@router.post("/{note_id}/star")
def toggle_star(note_id: str, request: Request) -> NoteOut:
    """#273: star is a long-lived marker (unlike pin's ordering role)."""
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"starred": not note["starred"]})
    assert note
    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/snooze")
def snooze_note(note_id: str, body: SnoozeIn, request: Request) -> NoteOut:
    """#14: hide a note until a preset or timestamp; an empty body wakes it."""
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"snoozed_until": _resolve_snooze(body.until)})
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
def trash_note(note_id: str, request: Request) -> dict:
    """#274: DELETE trashes the note instead of destroying it.

    The row (and its audio) survives until the retention purge or an explicit
    purge, so Undo in the UI is a restore, not a resurrection ritual. The
    vault mirror drops the file immediately — trashed notes must not linger
    in Obsidian.
    """
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"trashed_at": now_iso()})
    assert note
    markdown.remove_note(st.cfg.paths, note)
    st.bus.publish("note.updated", note)
    return {"ok": True, "id": note_id}


@router.post("/{note_id}/restore")
def restore_note(note_id: str, request: Request) -> NoteOut:
    """Take a note back out of the trash."""
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.update_note(note_id, {"trashed_at": None})
    assert note
    # Re-mirror: trash removed the vault file, so restore must put it back.
    markdown.sync_note(st.cfg.paths, note)
    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/purge")
def purge_note(note_id: str, request: Request) -> dict:
    """Hard-delete a trashed note now, skipping the retention window."""
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    note = st.db.delete_note(
        note_id, audio_root=st.cfg_audio_dir(), attachments_root=st.cfg_attachments_dir()
    )
    assert note
    markdown.remove_note(st.cfg.paths, note)
    st.bus.publish("note.deleted", {"id": note_id})
    return {"ok": True, "id": note_id}


trash_router = APIRouter(prefix="/api/trash", tags=["notes"])


@trash_router.get("")
def list_trash(request: Request) -> list[NoteOut]:
    st = request.app.state.st
    return [_out(n) for n in st.db.trashed_notes()]


@trash_router.delete("/{note_id}")
def trash_purge(note_id: str, request: Request) -> dict:
    return purge_note(note_id, request)


@trash_router.post("/empty")
def trash_empty(request: Request) -> dict:
    """Purge every trashed note immediately."""
    st = request.app.state.st
    purged = 0
    for note in st.db.trashed_notes(limit=1000):
        st.db.delete_note(
            note["id"], audio_root=st.cfg_audio_dir(), attachments_root=st.cfg_attachments_dir()
        )
        markdown.remove_note(st.cfg.paths, note)
        st.bus.publish("note.deleted", {"id": note["id"]})
        purged += 1
    return {"ok": True, "purged": purged}


@router.get("/{note_id}/collections")
def note_collections(note_id: str, request: Request) -> list[dict]:
    """Collections this note belongs to (drawer membership chips)."""
    st = request.app.state.st
    if not st.db.get_note(note_id):
        raise HTTPException(404, "note not found")
    return st.db.collections_for_note(note_id)


@router.get("/{note_id}/links")
def get_note_links(note_id: str, request: Request) -> dict:
    """#22: outgoing wikilinks and backlinks for a note."""
    st = request.app.state.st
    if not st.db.get_note(note_id):
        raise HTTPException(404, "note not found")
    outgoing, backlinks = st.db.note_links(note_id)
    return {"outgoing": [_out(n) for n in outgoing], "backlinks": [_out(n) for n in backlinks]}


@router.get("/{note_id}/similar")
def get_similar_notes(
    note_id: str,
    request: Request,
    limit: int = Query(8, ge=1, le=50),
) -> list[NoteOut]:
    """#320/#23: nearest notes by embedding cosine, for the drawer's
    related-notes strip. Notes without a stored embedding get a query-time
    vector — nothing is persisted here."""
    from ..services.similar import find_similar

    st = request.app.state.st
    if not st.db.get_note(note_id):
        raise HTTPException(404, "note not found")
    return [NoteOut(**n) for n in find_similar(st.db, st.cfg, note_id, limit=limit)]


@router.get("/{note_id}/versions")
def list_note_versions(note_id: str, request: Request) -> list[dict]:
    """#19: snapshots of title/summary/raw_text, oldest first."""
    st = request.app.state.st
    if not st.db.get_note(note_id):
        raise HTTPException(404, "note not found")
    return st.db.note_versions(note_id)


class EnrichFeedbackIn(BaseModel):
    """#255: -1 for a bad enrichment, 1 for a good one, 0 to clear."""
    feedback: int = Field(ge=-1, le=1)


@router.patch("/{note_id}/enrich-feedback")
def set_enrich_feedback(note_id: str, request: Request, body: EnrichFeedbackIn) -> NoteOut:
    """Record a verdict on this note's enrichment.

    Its own endpoint rather than the generic PATCH so the value is bounded —
    `enrich_feedback` is a three-state column, and a typo'd `feedback: 7`
    should not become a row nobody can query.
    """
    st = request.app.state.st
    note = st.db.update_note(note_id, {"enrich_feedback": body.feedback})
    if not note:
        raise HTTPException(404, "note not found")
    _bus(request).publish("note.updated", note)
    return NoteOut(**note)


@router.post("/{note_id}/versions/{version_id}/revert")
def revert_note_version(note_id: str, version_id: int, request: Request) -> NoteOut:
    """Restore title/summary/raw_text from a snapshot.

    update_note snapshots the current content first, so a revert is itself
    undoable — the history grows by one entry, nothing is destroyed.
    """
    st = request.app.state.st
    version = st.db.get_note_version(note_id, version_id)
    if not version:
        raise HTTPException(404, "version not found")
    note = st.db.update_note(
        note_id,
        {
            "title": version["title"],
            "summary": version["summary"],
            "raw_text": version["raw_text"],
        },
    )
    assert note
    if note["status"] == "done":
        markdown.sync_note(st.cfg.paths, note)
    try:
        embed_note(note, st.db, st.cfg)
    except Exception:
        log.warning("re-embed failed after revert of note %s", note_id, exc_info=True)
    st.bus.publish("note.updated", note)
    return _out(note)


@router.post("/{note_id}/regenerate")
async def regenerate_note(note_id: str, body: RegenerateIn, request: Request) -> NoteOut:
    """#20: re-run enrichment (title/summary/tags) for this note.

    Accepts a one-off model override so the user can pick a different model
    without changing their default. Tasks and raw_text are untouched.
    """
    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    if not (note.get("raw_text") or "").strip():
        raise HTTPException(400, "note has no content to enrich")
    if st.cfg.llm.provider == "none":
        raise HTTPException(400, "no LLM provider configured — set one in settings")

    from dataclasses import replace as dc_replace

    llm_cfg = st.cfg.llm
    if body.model:
        llm_cfg = dc_replace(llm_cfg, model=body.model)

    from ..services import llm as llm_svc

    try:
        enriched = await llm_svc.enrich_chain(
            note["raw_text"],
            llm_cfg,
            few_shot=build_few_shot(st.db),
        )
    except llm_svc.LLMUnavailable as exc:
        raise HTTPException(502, f"model unreachable: {exc}") from exc

    note = st.db.update_note(
        note_id,
        {
            "title": enriched["title"],
            "summary": enriched["summary"],
            "tags": enriched["tags"],
            "review_state": "enriched",
            "enrich_confidence": enriched.get("confidence"),
        },
    )
    assert note
    markdown.sync_note(st.cfg.paths, note)
    try:
        embed_note(note, st.db, st.cfg)
    except Exception:
        log.warning("re-embed failed after regenerate of note %s", note_id, exc_info=True)
    st.bus.publish("note.updated", note)
    return _out(note)


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


@router.get("/{note_id}/audio")
def get_note_audio(note_id: str, request: Request):
    """Stream the raw capture audio so the UI can offer click-to-seek playback."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    audio = note.get("audio_path")
    if not audio or not Path(audio).exists():
        raise HTTPException(404, "no audio on file for this note")
    ext = Path(audio).suffix.lower().lstrip(".")
    media = {"webm": "audio/webm", "ogg": "audio/ogg", "oga": "audio/ogg", "wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "mp4": "audio/mp4", "opus": "audio/opus"}.get(ext, "application/octet-stream")
    return FileResponse(audio, media_type=media)


MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB — screenshots/PDFs, not video


@router.post("/{note_id}/attachments")
async def upload_attachment(note_id: str, request: Request) -> dict:
    """#24: attach a file (drag-and-drop in the UI) onto a note.

    Filenames are reduced to their basename and stored under
    attachments/{note_id}/ — a crafted "../" name cannot escape the root.
    """
    import uuid
    from pathlib import Path

    from starlette.datastructures import UploadFile

    st = request.app.state.st
    note = st.db.get_note(note_id)
    if not note:
        raise HTTPException(404, "note not found")
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(422, "multipart form must carry a 'file' field")
    data = await upload.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, "attachment exceeds the 25 MB limit")
    if not data:
        raise HTTPException(422, "empty file")

    safe_name = Path(upload.filename or "unnamed").name or "unnamed"
    target_dir = Path(st.cfg_attachments_dir()) / note_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # Prefix with a short uuid so two "Screenshot.png" uploads cannot collide.
    target = target_dir / f"{uuid.uuid4().hex[:8]}-{safe_name}"
    target.write_bytes(data)

    att = st.db.insert_attachment(
        note_id, safe_name, str(target), upload.content_type, len(data)
    )
    st.bus.publish("note.updated", st.db.get_note(note_id) or note)
    return att


@router.get("/{note_id}/attachments")
def list_attachments(note_id: str, request: Request) -> list[dict]:
    st = request.app.state.st
    if not st.db.get_note(note_id):
        raise HTTPException(404, "note not found")
    return st.db.attachments_for(note_id)


@router.get("/{note_id}/attachments/{att_id}/file")
def download_attachment(note_id: str, att_id: str, request: Request):
    from pathlib import Path

    from fastapi.responses import FileResponse

    st = request.app.state.st
    att = st.db.get_attachment(att_id)
    if not att or att["note_id"] != note_id or not Path(att["path"]).exists():
        raise HTTPException(404, "attachment not found")
    return FileResponse(
        att["path"],
        media_type=att["mime"] or "application/octet-stream",
        filename=att["filename"],
    )


@router.delete("/{note_id}/attachments/{att_id}")
def remove_attachment(note_id: str, att_id: str, request: Request) -> dict:
    from pathlib import Path

    st = request.app.state.st
    att = st.db.get_attachment(att_id)
    if not att or att["note_id"] != note_id:
        raise HTTPException(404, "attachment not found")
    st.db.delete_attachment(att_id)
    try:
        Path(att["path"]).unlink(missing_ok=True)
    except OSError:
        log.warning("could not remove attachment file %s", att["path"], exc_info=True)
    st.bus.publish("note.updated", st.db.get_note(note_id) or {"id": note_id})
    return {"ok": True, "id": att_id}


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
