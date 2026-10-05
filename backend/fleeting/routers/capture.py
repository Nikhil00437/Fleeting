"""Capture endpoints — the front door of the app.

Every capture returns immediately with a pending note; processing happens in
the background and reaches the UI via SSE events.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..db import new_id, now_iso
from ..models import CaptureTextIn, CaptureYouTubeIn, NoteOut
from ..services import templates as tmpl

router = APIRouter(prefix="/api/capture", tags=["capture"])

AUDIO_MAX_BYTES = 50 * 1024 * 1024
ALLOWED_AUDIO_EXT = {".webm", ".ogg", ".oga", ".wav", ".mp3", ".m4a", ".mp4", ".opus"}

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{6,})"
)


def _now() -> str:
    return now_iso()


def _resolve_template(body: CaptureTextIn | CaptureYouTubeIn | None = None, *, template: str | None = None, mode: str | None = None) -> tuple[dict, str | None, str | None]:
    """Template lookup + mode validation shared by all capture paths."""
    template = template if template is not None else (body.template if body else None)
    mode = mode if mode is not None else (body.mode if body else None)
    if mode is not None and mode not in tmpl.OUTPUT_MODES:
        raise HTTPException(422, f"unknown output mode '{mode}' (want one of {', '.join(tmpl.OUTPUT_MODES)})")
    if not template:
        return {}, None, mode
    t = tmpl.get_template(template)
    if t is None:
        raise HTTPException(422, f"unknown template '{template}'")
    if mode is None and isinstance(t.get("mode"), str):
        mode = t["mode"]
        if mode not in tmpl.OUTPUT_MODES:
            raise HTTPException(422, f"template '{template}' has bad mode '{mode}'")
    return t, template, mode


@router.post("/text")
def capture_text(body: CaptureTextIn, request: Request) -> NoteOut:
    st = request.app.state.st
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "capture text is empty")

    # pasting a youtube link into the text box routes to the youtube pipeline
    yt_match = YOUTUBE_RE.search(text)
    if yt_match and len(text) < 200 and text.strip().startswith(("http", "www.", "youtu")):
        return _capture_youtube(request, f"https://youtu.be/{yt_match.group(1)}", body.capture_id, body.source_title, body.template, body.mode)

    if body.capture_id:
        existing = st.db.get_note_by_capture_id(body.capture_id)
        if existing:
            return NoteOut(**existing)

    template, tname, mode = _resolve_template(body)
    if mode and mode != "raw":
        text = tmpl.apply_output_mode(text, mode)
    merged_tags = list(dict.fromkeys([*(template.get("tags") or []), *body.tags]))[:6]
    note = st.db.insert_note(
        {
            "id": new_id(),
            "type": template.get("type") or "text",
            "title": body.title.strip()[:120],
            "raw_text": text,
            "tags": merged_tags,
            "source": {"template": {"name": tname, "prompt": template.get("prompt"), "mode": mode}} if tname else {},
            "status": "pending",
            "capture_id": body.capture_id,
            "source_title": body.source_title,
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)


@router.post("/audio")
async def capture_audio(
    request: Request,
    file: UploadFile = File(...),
    template: str | None = Form(default=None),
    mode: str | None = Form(default=None),
    language: str | None = Form(default=None),
) -> NoteOut:
    st = request.app.state.st
    data = await file.read()
    if not data:
        raise HTTPException(422, "empty audio upload")
    if len(data) > AUDIO_MAX_BYTES:
        raise HTTPException(413, "audio too large (max 50 MB)")

    ext = Path(file.filename or "audio.webm").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        ext = ".webm"

    tmeta, tname, mode = _resolve_template(template=template, mode=mode)

    note_id = new_id()
    audio_path = st.cfg_audio_dir() / f"{note_id}{ext}"
    audio_path.write_bytes(data)

    note = st.db.insert_note(
        {
            "id": note_id,
            "type": tmeta.get("type") or "voice",
            "tags": list(tmeta.get("tags") or [])[:6],
            "audio_path": str(audio_path),
            "raw_text": "",
            "source": {
                "bytes": len(data),
                "filename": file.filename,
                **({"template": {"name": tname, "prompt": tmeta.get("prompt"), "mode": mode}} if tname or mode else {}),
                **({"language": language} if language else {}),
            },
            "status": "pending",
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)


@router.post("/preview")
async def preview_transcription(request: Request, file: UploadFile = File(...)) -> dict:
    """#8: transcribe the audio-so-far while the user is still talking.

    Full-blob-so-far re-transcription on a timer — with faster-whisper on a
    decent CPU it's near-realtime for short clips; the ponytail ceiling is
    that segment streaming would be more efficient if latency matters.
    """
    import asyncio
    import tempfile

    st = request.app.state.st
    data = await file.read()
    if not data:
        return {"text": ""}
    if len(data) > AUDIO_MAX_BYTES:
        raise HTTPException(413, "preview audio too large")
    ext = Path(file.filename or "preview.webm").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        ext = ".webm"
    tmp = Path(tempfile.mkstemp(suffix=ext, prefix="fleeting-preview-")[1])
    try:
        tmp.write_bytes(data)
        result = await asyncio.to_thread(st.transcriber.transcribe_file, tmp)
        return {"text": result.get("text", "")}
    except Exception as exc:
        raise HTTPException(502, f"preview transcription failed: {exc}")
    finally:
        tmp.unlink(missing_ok=True)


@router.post("/youtube")
def capture_youtube(body: CaptureYouTubeIn, request: Request) -> NoteOut:
    return _capture_youtube(request, body.url, body.capture_id, body.source_title, body.template, body.mode)


def _capture_youtube(request: Request, raw_url: str, capture_id: str | None = None, source_title: str | None = None, template: str | None = None, mode: str | None = None) -> NoteOut:
    st = request.app.state.st
    match = YOUTUBE_RE.search(raw_url)
    if not match:
        raise HTTPException(422, "that doesn't look like a YouTube URL")
    if capture_id:
        existing = st.db.get_note_by_capture_id(capture_id)
        if existing:
            return NoteOut(**existing)
    url = f"https://youtu.be/{match.group(1)}"
    tmeta, tname, mode = _resolve_template(template=template, mode=mode)
    note = st.db.insert_note(
        {
            "id": new_id(),
            "type": "youtube",
            "raw_text": "",
            "tags": list(tmeta.get("tags") or [])[:6],
            "source": {"url": url, **({"template": {"name": tname, "prompt": tmeta.get("prompt"), "mode": mode}} if tname or mode else {})},
            "status": "pending",
            "capture_id": capture_id,
            "source_title": source_title,
            "created_at": _now(),
            "updated_at": _now(),
        }
    )
    st.processor.enqueue(note["id"])
    st.bus.publish("note.created", note)
    return NoteOut(**note)
