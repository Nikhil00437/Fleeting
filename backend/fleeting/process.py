"""Background capture-processing pipeline.

Captures are inserted immediately (status=pending) and the API returns; this
worker picks them up, runs transcription / YouTube ingest / LLM enrichment,
flips the note to done, mirrors it to the Markdown vault, and broadcasts SSE
events so the UI updates live. Blocking work (whisper, ffmpeg, yt-dlp) runs
in threads so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from .config import Config
from .db import Database, now_iso
from .events import EventBus
from .services import llm, markdown
from .services.transcribe import Transcriber, TranscriptionError
from .services.youtube import YouTubeError, ingest as yt_ingest

log = logging.getLogger("fleeting.process")


class Processor:
    def __init__(self, db: Database, cfg: Config, bus: EventBus, transcriber: Transcriber):
        self.db = db
        self.cfg = cfg
        self.bus = bus
        self.transcriber = transcriber
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self.active_id: str | None = None

    # ---- lifecycle -----------------------------------------------------

    def start(self) -> None:
        self._worker_task = asyncio.get_running_loop().create_task(self._worker_loop())

    def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()

    def enqueue(self, note_id: str) -> None:
        self.queue.put_nowait(note_id)

    async def recover_unfinished(self) -> int:
        """Re-enqueue notes left pending/processing by a previous run."""
        unfinished = self.db.notes_in_status("pending", "processing")
        for note in unfinished:
            self.db.update_note(note["id"], {"status": "pending", "error": None})
            self.enqueue(note["id"])
        return len(unfinished)

    # ---- worker ---------------------------------------------------------

    async def _worker_loop(self) -> None:
        while True:
            note_id = await self.queue.get()
            self.active_id = note_id
            try:
                await self._process(note_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected failure processing note %s", note_id)
                self._fail(note_id, "internal error — see server log")
            finally:
                self.active_id = None
                self.queue.task_done()

    async def _set_status(self, note_id: str, status: str, error: str | None = None) -> None:
        note = self.db.update_note(note_id, {"status": status, "error": error})
        if note:
            self.bus.publish("note.updated", note)

    def _fail(self, note_id: str, error: str) -> None:
        note = self.db.update_note(note_id, {"status": "failed", "error": error})
        if note:
            self.bus.publish("note.updated", note)

    async def _process(self, note_id: str) -> None:
        note = self.db.get_note(note_id)
        if not note:
            return
        started = time.monotonic()
        await self._set_status(note_id, "processing")

        source = dict(note.get("source") or {})
        try:
            # 1) raw content acquisition
            if note["type"] == "voice" and note.get("audio_path"):
                await self._set_stage(note_id, "transcribing")
                result = await asyncio.to_thread(
                    self.transcriber.transcribe_file, note["audio_path"]
                )
                raw_text = result["text"]
                if not raw_text:
                    raise TranscriptionError("transcription produced no text (silent audio?)")
                source["transcription"] = {
                    "duration": result["duration"],
                    "language": result["language"],
                }
                note = self.db.update_note(note_id, {"raw_text": raw_text, "source": source})
            elif note["type"] == "youtube" and source.get("url"):
                await self._set_stage(note_id, "fetching video")
                ingested = await asyncio.to_thread(
                    yt_ingest, source["url"], self.cfg.youtube, self.transcriber
                )
                source.update(ingested["source"])
                note = self.db.update_note(note_id, {"raw_text": ingested["text"], "source": source})

            note = note or self.db.get_note(note_id)
            if not note or not (note.get("raw_text") or "").strip():
                self._fail(note_id, "nothing to process — capture had no content")
                return

            # 2) enrichment
            await self._set_stage(note_id, "organizing")
            try:
                enriched = await llm.enrich(note["raw_text"], self.cfg.llm)
                source["enrichment"] = "local-llm"
            except llm.LLMUnavailable as exc:
                log.info("LLM unavailable (%s) — heuristic fallback for %s", exc, note_id)
                enriched = llm.heuristic_enrich(note["raw_text"])
                source["enrichment"] = "heuristic"

            # 3) persist structured fields
            changes = {
                "title": enriched["title"],
                "summary": enriched["summary"],
                "tags": enriched["tags"],
                "source": source,
                "status": "done",
                "error": None,
                "processed_at": now_iso(),
            }
            note = self.db.update_note(note_id, changes)

            default_repo = source.get("repo")
            for item in enriched.get("action_items") or []:
                if isinstance(item, str):
                    item = {"text": item, "priority": "P2", "due_date": None, "repo": None}
                self.db.insert_task({
                    "note_id": note["id"] if note else note_id,
                    "text": item.get("text", ""),
                    "priority": item.get("priority", "P2"),
                    "due_date": item.get("due_date"),
                    "repo": item.get("repo") or default_repo,
                })
            note = self.db.get_note(note_id)

            # 4) vault mirror + notify
            if note:
                markdown.sync_note(self.cfg.paths, note)
                self._maybe_notify(note)
            log.info("note %s processed in %.1fs", note_id, time.monotonic() - started)
            self.bus.publish("note.updated", note)
        except (TranscriptionError, YouTubeError) as exc:
            self._fail(note_id, str(exc))
        except Exception as exc:
            log.exception("processing note %s failed", note_id)
            self._fail(note_id, f"{type(exc).__name__}: {exc}")

    async def _set_stage(self, note_id: str, stage: str) -> None:
        note = self.db.get_note(note_id)
        if note:
            source = dict(note.get("source") or {})
            source["stage"] = stage
            note = self.db.update_note(note_id, {"source": source})
            self.bus.publish("note.updated", note)

    def _maybe_notify(self, note: dict) -> None:
        if not self.cfg.notifications.desktop:
            return
        from .notify import send

        title = note.get("title") or "Capture processed"
        body = (note.get("summary") or "ready")[:120]
        send("Fleeting", f"{title} — {body}")
