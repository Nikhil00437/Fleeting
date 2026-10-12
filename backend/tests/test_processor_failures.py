"""What a capture does when the work under it fails.

`Processor._fail` exists and sets `status="failed"` with a reason, but nothing
drove a capture into it. The failure paths are the ones users hit first — a
voice memo transcribed on a machine where whisper will not load, an LLM that
stopped answering mid-afternoon — and they are exactly the paths that go
unexercised while everything is healthy.

Every failure here is forced deterministically. A chaos switch that failed calls
at random would explore the same code less reliably and would not tell you,
afterwards, which failure produced the note you are looking at. See
`test_chaos.py` for the manual tool that does explore them at runtime.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.process import Processor
from fleeting.services.transcribe import TranscriptionError


class Boom:
    """A transcriber whose model will not load, the common real failure."""

    def __init__(self, exc: Exception | None = None) -> None:
        self.loaded_model_size = "base"
        self.cfg = Config().transcribe
        self.exc = exc or TranscriptionError("whisper failed: model load failed")

    def is_ready(self) -> bool:
        return True

    def transcribe_file(self, path, language=None):
        raise self.exc


@pytest.fixture
def proc(tmp_path) -> Processor:
    db = Database(tmp_path / "f.db")
    db.migrate()
    cfg = Config()
    cfg.llm.provider = "none"
    p = Processor(db, cfg, EventBus(), Boom())
    return p


def _voice_note(db: Database, cfg: Config) -> str:
    d = Path(str(cfg.paths.vault_dir))
    audio = d / "memo.wav"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF0000WAVE")
    cfg.paths.vault_dir = str(d / "vault")
    note = db.insert_note(
        {"raw_text": "", "type": "voice", "audio_path": str(audio)}
    )
    return note["id"] if isinstance(note, dict) else note


async def _run(proc: Processor, note_id: str) -> dict:
    proc.start()
    proc.enqueue(note_id)
    for _ in range(200):
        note = proc.db.get_note(note_id)
        if note and note.get("status") in ("done", "failed"):
            return note
        await asyncio.sleep(0.01)
    raise AssertionError("capture never settled")


@pytest.mark.anyio
async def test_a_transcription_failure_fails_the_capture_with_a_reason(proc) -> None:
    note_id = _voice_note(proc.db, proc.cfg)
    note = await _run(proc, note_id)
    assert note["status"] == "failed"
    # The reason has to reach the user; a bare "failed" is useless at 2am.
    assert "whisper" in (note.get("error") or "")


@pytest.mark.anyio
async def test_a_failed_capture_keeps_the_audio_rather_than_deleting_it(proc) -> None:
    """#91 deletes the audio only after a successful transcription.

    Losing the recording when the *model* failed would destroy the only copy
    of the user's memo — the one thing they cannot retype.
    """
    note_id = _voice_note(proc.db, proc.cfg)
    before = proc.db.get_note(note_id)
    path = Path(before["audio_path"])
    await _run(proc, note_id)
    after = proc.db.get_note(note_id)
    assert after["audio_path"] == str(path)
    assert path.exists(), "the audio was deleted despite the failure"


@pytest.mark.anyio
async def test_a_failure_publishes_the_failed_status(proc) -> None:
    """Otherwise the card sits on "processing" in the UI forever.

    Asserting on the payload, not just that *some* `note.updated` was seen:
    `_set_status` publishes one on the way in, so counting events passes even
    with the publish on failure deleted entirely.
    """
    payloads: list[dict] = []
    note_id = _voice_note(proc.db, proc.cfg)
    proc.bus.subscribe("note.updated", payloads.append)
    await _run(proc, note_id)
    assert any(p.get("status") == "failed" for p in payloads), payloads


@pytest.mark.anyio
async def test_audio_is_kept_by_default(proc) -> None:
    """#91 with `keep_audio` left alone, which is the shipped default: keep.

    The complement of the failure test above, and of the deletion test below —
    a memo transcript is lossy, so the recording stays unless asked otherwise.
    """
    note_id = _voice_note(proc.db, proc.cfg)
    audio = Path(proc.db.get_note(note_id)["audio_path"])
    proc.transcriber.transcribe_file = lambda path, language=None: {
        "text": "the memo",
        "duration": 1.0,
        "language": "en",
    }
    proc.db.update_note(note_id, {"status": "pending"})
    note = await _run(proc, note_id)
    assert note["status"] == "done"
    assert note["audio_path"] == str(audio)
    assert audio.exists()


@pytest.mark.anyio
async def test_audio_is_deleted_when_keep_audio_is_off(proc) -> None:
    """The other half of #91, and the thing that leaks a file per capture."""
    proc.cfg.transcribe.keep_audio = False
    note_id = _voice_note(proc.db, proc.cfg)
    audio = Path(proc.db.get_note(note_id)["audio_path"])
    proc.transcriber.transcribe_file = lambda path, language=None: {
        "text": "the memo",
        "duration": 1.0,
        "language": "en",
    }
    proc.db.update_note(note_id, {"status": "pending"})
    note = await _run(proc, note_id)
    assert note["status"] == "done"
    assert note["audio_path"] is None
    assert not audio.exists()


@pytest.mark.anyio
async def test_an_llm_failure_still_produces_an_enriched_note(proc) -> None:
    """The LLM is an enhancement, not a dependency.

    With no model reachable the capture must still land with a title and tags
    from the heuristics — losing the note because enrichment failed would make
    a model outage look like data loss.
    """
    note_id = proc.db.insert_note(
        {
            "raw_text": "Remember to email the landlord about the lease renewal",
            "type": "text",
            "title": "email the landlord",
        }
    )["id"]
    note = await _run(proc, note_id)
    assert note["status"] == "done"
    assert (note.get("title") or "").strip()
    assert note.get("tags")


@pytest.mark.anyio
async def test_a_capture_with_no_content_fails_rather_than_hanging(proc) -> None:
    """Empty in, empty out — but it must settle, not sit processing forever."""
    note_id = proc.db.insert_note({"raw_text": "   ", "type": "voice"})["id"]
    note = await _run(proc, note_id)
    assert note["status"] == "failed"
    assert note.get("error")


@pytest.mark.anyio
async def test_retrying_a_failed_capture_recovers_it(proc) -> None:
    """The user fixes the model and hits retry; it has to actually work."""
    note_id = _voice_note(proc.db, proc.cfg)
    failed = await _run(proc, note_id)
    assert failed["status"] == "failed"

    # Whisper recovers.
    proc.transcriber.transcribe_file = lambda path, language=None: {
        "text": "the memo, at last",
        "duration": 1.0,
        "language": "en",
    }
    proc.db.update_note(note_id, {"status": "pending"})
    note = await _run(proc, note_id)
    assert note["status"] == "done"
    assert "memo" in (note.get("raw_text") or "")