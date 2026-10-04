"""Capture queue must not be a single serial slot.

One worker drains the queue, and a YouTube capture with whisper fallback can
chain ~22 minutes of subprocess work (yt-dlp metadata + subs, possibly an
audio download, ffmpeg, then whisper). Every other capture waited behind it,
with no feedback in the UI beyond a queue counter.

Also: the queue was unbounded, so a burst of captures grew memory without
limit, and `enqueue` could be called twice for the same note (reprocess), so
one note could be processed twice concurrently.
"""

from __future__ import annotations

import asyncio

import pytest

import fleeting.process as fproc
from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.process import Processor


class FakeTranscriber:
    """Never touches the network; blocks on an event the test controls."""

    def __init__(self) -> None:
        self.gate: asyncio.Event | None = None
        self.started: list[str] = []
        self.loaded_model_size = "base"
        self.cfg = Config().transcribe

    def is_ready(self) -> bool:
        return True

    def transcribe_file(self, path, language=None):
        self.started.append(str(path))
        if self.gate is not None:
            # Blocking sleep in a thread, exactly like the real call.
            import time

            while not self.gate.is_set():
                time.sleep(0.01)
        return {"text": "hello world", "duration": 1.0, "language": "en"}


@pytest.fixture
def proc(tmp_path) -> Processor:
    db = Database(tmp_path / "p.db")
    db.migrate()
    cfg = Config()
    cfg.llm.provider = "none"
    t = FakeTranscriber()
    p = Processor(db, cfg, EventBus(), t)
    p._test_transcriber = t  # type: ignore[attr-defined]
    return p


def _voice_note(db: Database, cfg: Config, text: str = "memo") -> str:
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp())
    audio = d / f"{text}.wav"
    audio.write_bytes(b"RIFF0000WAVE")
    cfg.paths.vault_dir = str(d / "vault")
    note = db.insert_note(
        {
            "raw_text": "",
            "type": "voice",
            "audio_path": str(audio),
            "source": {"filename": audio.name},
        }
    )
    return note["id"] if isinstance(note, dict) else note


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_two_captures_are_processed_concurrently(proc) -> None:
    """The headline bug: a slow capture must not block the next one."""
    t = proc._test_transcriber  # type: ignore[attr-defined]
    t.gate = asyncio.Event()

    n1 = _voice_note(proc.db, proc.cfg, "one")
    n2 = _voice_note(proc.db, proc.cfg, "two")

    proc.start()
    proc.enqueue(n1)
    proc.enqueue(n2)
    try:
        # Wait for BOTH to reach the blocking transcribe call.
        for _ in range(200):
            if len(t.started) >= 2:
                break
            await asyncio.sleep(0.02)

        assert len(t.started) == 2, (
            f"only {len(t.started)} capture(s) started — "
            "the second is queued behind the first"
        )
    finally:
        t.gate.set()
        proc.stop()


@pytest.mark.anyio
async def test_one_slow_capture_does_not_delay_a_text_note(proc) -> None:
    """A cheap capture completes while a slow one is still running."""
    t = proc._test_transcriber  # type: ignore[attr-defined]
    t.gate = asyncio.Event()

    slow = _voice_note(proc.db, proc.cfg, "slow")
    note = proc.db.insert_note({"raw_text": "quick thought", "type": "text"})
    quick = note["id"] if isinstance(note, dict) else note

    proc.start()
    proc.enqueue(slow)
    await asyncio.sleep(0.05)
    proc.enqueue(quick)
    try:
        for _ in range(300):
            if proc.db.get_note(quick)["status"] in ("done", "failed"):
                break
            await asyncio.sleep(0.02)

        assert proc.db.get_note(slow)["status"] == "processing", "slow note should still be running"
        assert (
            proc.db.get_note(quick)["status"] == "done"
        ), "quick note was blocked behind the slow one"
    finally:
        t.gate.set()
        proc.stop()


# ---------------------------------------------------------------------------
# bounds + dedupe
# ---------------------------------------------------------------------------


def test_queue_is_bounded(proc) -> None:
    assert proc.queue.maxsize > 0, "unbounded queue grows memory without limit"


def test_enqueue_refills_after_a_drain(proc) -> None:
    """A full queue must accept work again once a slot frees."""
    proc.queue = asyncio.Queue(maxsize=2)
    proc._queued.clear()
    assert proc.enqueue("a") is True
    assert proc.enqueue("b") is True
    assert proc.enqueue("c") is False, "enqueue must report a full queue"

    proc.queue.get_nowait()
    proc._queued.discard("a")
    assert proc.enqueue("c") is True


def test_enqueue_returns_false_when_full(proc) -> None:
    """Callers need to know the note was refused, not silently dropped."""
    proc.queue = asyncio.Queue(maxsize=1)
    proc._queued.clear()
    assert proc.enqueue("a") is True
    assert proc.enqueue("b") is False
    assert proc.queue.qsize() == 1


@pytest.mark.anyio
async def test_same_note_is_not_queued_twice(proc) -> None:
    """Reprocess calls enqueue on an id that may already be pending."""
    n = proc.db.insert_note({"raw_text": "dupe", "type": "text"})
    nid = n["id"] if isinstance(n, dict) else n
    proc.enqueue(nid)
    proc.enqueue(nid)
    assert proc.queue.qsize() == 1


@pytest.mark.anyio
async def test_enqueue_after_completion_works_again(proc) -> None:
    """Dedupe must not permanently block a note once it has been processed."""
    n = proc.db.insert_note({"raw_text": "again", "type": "text"})
    nid = n["id"] if isinstance(n, dict) else n
    proc.start()
    proc.enqueue(nid)
    for _ in range(200):
        if proc.db.get_note(nid)["status"] == "done":
            break
        await asyncio.sleep(0.02)
    assert proc.db.get_note(nid)["status"] == "done"
    try:
        proc.enqueue(nid)
        assert proc.queue.qsize() == 1
    finally:
        proc.stop()


@pytest.mark.anyio
async def test_active_ids_reflects_in_flight_notes(proc) -> None:
    t = proc._test_transcriber  # type: ignore[attr-defined]
    t.gate = asyncio.Event()
    n1 = _voice_note(proc.db, proc.cfg, "a")
    n2 = _voice_note(proc.db, proc.cfg, "b")
    proc.start()
    proc.enqueue(n1)
    proc.enqueue(n2)
    try:
        for _ in range(200):
            if len(t.started) >= 2:
                break
            await asyncio.sleep(0.02)
        assert len(set(proc.active_ids)) == 2, f"active_ids={proc.active_ids}"
    finally:
        t.gate.set()
        proc.stop()