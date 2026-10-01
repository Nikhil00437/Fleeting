"""Capture endpoints — the front door of the app.

Every capture returns immediately with a pending note; processing happens in
the background and reaches the UI via SSE events.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ..db import new_id, now_iso
from ..models import CaptureTextIn, CaptureYouTubeIn, NoteOut

router = APIRouter(prefix="/api/capture", tags=["capture"])

AUDIO_MAX_BYTES = 50 * 1024 * 1024
ALLOWED_AUDIO_EXT = {".webm", ".ogg", ".oga", ".wav", ".mp3", ".m4a", ".mp4", ".opus"}

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{6,})"
)


def _now() -> str:
    return now_iso()


@router.post("/text")
def capture_text(body: CaptureTextIn, request: Request) -> NoteOut:
    st = request.app.state.st
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "capture text is empty")

    # pasting a youtube link into the text box routes to the youtube pipeline
    yt_match = YOUTUBE_RE.search(text)
    if yt_match and len(text) < 200 and text.strip().startswith(("http", "www.", "youtu")):
        return _capture_youtube(request, f"https://youtu.be/{yt_match.group(1)}")

    note = st.db.insert_note(
        {
            "id": new_id(),
            "type": "text",
            "title": body.title.strip()[:120],
            "raw_text": text,
            "tags": body.tags[:6],
            "source": {},
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)


@router.post("/audio")
async def capture_audio(request: Request, file: UploadFile = File(...)) -> NoteOut:
    st = request.app.state.st
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty audio upload")
    if len(data) > AUDIO_MAX_BYTES:
        raise HTTPException(413, "audio too large (max 50 MB)")

    ext = Path(file.filename or "audio.webm").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        ext = ".webm"

    note_id = new_id()
    audio_path = st.cfg_audio_dir() / f"{note_id}{ext}"
    audio_path.write_bytes(data)

    note = st.db.insert_note(
        {
            "id": note_id,
            "type": "voice",
            "audio_path": str(audio_path),
            "raw_text": "",
            "source": {"bytes": len(data), "filename": file.filename},
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)


@router.post("/youtube")
def capture_youtube(body: CaptureYouTubeIn, request: Request) -> NoteOut:
    return _capture_youtube(request, body.url)


def _capture_youtube(request: Request, raw_url: str) -> NoteOut:
    st = request.app.state.st
    match = YOUTUBE_RE.search(raw_url)
    if not match:
        raise HTTPException(422, "that doesn't look like a YouTube URL")
    url = f"https://youtu.be/{match.group(1)}"
    note = st.db.insert_note(
        {
            "id": new_id(),
            "type": "youtube",
            "raw_text": "",
            "source": {"url": url},
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)
