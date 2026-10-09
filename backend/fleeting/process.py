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
from pathlib import Path

from .config import Config
from .db import Database, now_iso
from .events import EventBus
from .services import llm, markdown
from .services.embeddings import embed_note
from .services.transcribe import Transcriber, TranscriptionError
from .services.youtube import YouTubeError, ingest as yt_ingest

log = logging.getLogger("fleeting.process")


class Processor:
    # ponytail: fixed at 2. A YouTube capture with whisper fallback chains
    # ~22 min of subprocess work, so 1 worker blocked everything behind it.
    # Raise if captures ever queue faster than they drain.
    WORKERS = 2
    # Bounded so a burst of captures cannot grow memory without limit.
    QUEUE_MAX = 500

    def __init__(self, db: Database, cfg: Config, bus: EventBus, transcriber: Transcriber):
        self.db = db
        self.cfg = cfg
        self.bus = bus
        self.transcriber = transcriber
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._worker_tasks: list[asyncio.Task] = []
        self._queued: set[str] = set()
        self._inflight: set[str] = set()
        self.active_ids: set[str] = set()

    @property
    def active_id(self) -> str | None:
        """Back-compat: the note currently being processed, if any."""
        return next(iter(self.active_ids), None)

    # ---- lifecycle -----------------------------------------------------

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._worker_tasks = [
            loop.create_task(self._worker_loop(i)) for i in range(self.WORKERS)
        ]

    def stop(self) -> None:
        for t in self._worker_tasks:
            t.cancel()
        self._worker_tasks = []

    def enqueue(self, note_id: str) -> bool:
        """Queue a note. False if it is already queued/in-flight, or the queue is full.

        Deduped because `reprocess` enqueues an id that may already be pending,
        and the queue is bounded so callers must be able to see a refusal.
        """
        if note_id in self._queued or note_id in self._inflight:
            return False
        try:
            self.queue.put_nowait(note_id)
        except asyncio.QueueFull:
            log.warning("capture queue full (%d) — rejected %s", self.QUEUE_MAX, note_id)
            self.bus.publish("note.updated", {"id": note_id, "queue_full": True})
            return False
        self._queued.add(note_id)
        return True

    async def recover_unfinished(self) -> int:
        """Re-enqueue notes left pending/processing by a previous run."""
        unfinished = self.db.notes_in_status("pending", "processing")
        for note in unfinished:
            self.db.update_note(note["id"], {"status": "pending", "error": None})
            self.enqueue(note["id"])
        return len(unfinished)

    # ---- worker ---------------------------------------------------------

    async def _worker_loop(self, worker: int = 0) -> None:
        while True:
            note_id = await self.queue.get()
            self._queued.discard(note_id)
            self._inflight.add(note_id)
            self.active_ids.add(note_id)
            try:
                await self._process(note_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected failure processing note %s", note_id)
                self._fail(note_id, "internal error — see server log")
            finally:
                self._inflight.discard(note_id)
                self.active_ids.discard(note_id)
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
                    self.transcriber.transcribe_file, note["audio_path"], source.get("language")
                )
                raw_text = result["text"]
                if not raw_text:
                    raise TranscriptionError("transcription produced no text (silent audio?)")
                transcription = {"duration": result["duration"], "language": result["language"]}
                if result.get("words"):
                    transcription["words"] = result["words"]  # #88
                if result.get("speakers"):
                    transcription["speakers"] = result["speakers"]  # #87
                self._patch_source(note_id, {"transcription": transcription})
                note = self.db.update_note(note_id, {"raw_text": raw_text})
                # #91 retention: drop the raw audio once it has served its
                # purpose, unless the user asked to keep it.
                if not self.cfg.transcribe.keep_audio and note["audio_path"]:
                    Path(note["audio_path"]).unlink(missing_ok=True)
                    note = self.db.update_note(note_id, {"audio_path": None})
                # #427: HUD output mode shapes the transcript
                mode = (source.get("template") or {}).get("mode")
                if mode and mode != "raw":
                    from .services.templates import apply_output_mode

                    raw_text = apply_output_mode(raw_text, mode)
                    note = self.db.update_note(note_id, {"raw_text": raw_text})
            elif note["type"] == "youtube" and source.get("url"):
                await self._set_stage(note_id, "fetching video")
                ingested = await asyncio.to_thread(
                    yt_ingest, source["url"], self.cfg.youtube, self.transcriber
                )
                self._patch_source(note_id, ingested["source"])
                raw_text = ingested["text"]
                mode = (source.get("template") or {}).get("mode")
                if mode and mode != "raw":
                    from .services.templates import apply_output_mode

                    raw_text = apply_output_mode(raw_text, mode)
                note = self.db.update_note(note_id, {"raw_text": raw_text})

            note = note or self.db.get_note(note_id)
            if not note or not (note.get("raw_text") or "").strip():
                self._fail(note_id, "nothing to process — capture had no content")
                return

            # 2) enrichment
            await self._set_stage(note_id, "enriching")
            if note.get("sensitive"):
                # #26: sensitive content never reaches any model — not the
                # local LLM, not a remote one behind a custom provider, and
                # not the embedding index either (below).
                enriched = llm.heuristic_enrich(note["raw_text"])
                source["enrichment"] = "heuristic-sensitive"
            else:
                try:
                    template_prompt = (note.get("source") or {}).get("template", {}).get("prompt")
                    # #266: walks llm.fallback_models before giving up on the
                    # model, so one unreachable model does not silently drop
                    # every capture to heuristics.
                    enriched = await llm.enrich_chain(
                        note["raw_text"], self.cfg.llm, prompt=template_prompt
                    )
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
                "source": self._patch_source(note_id, source),
                "status": "done",
                "error": None,
                "processed_at": now_iso(),
                # #96: the model's own verdict on the enrichment, or None. A
                # reprocess must clear a stale score, so this is always written.
                "enrich_confidence": enriched.get("confidence"),
            }
            # #474/#424: heuristic enrichment is the low-confidence path — drop
            # the note into the review queue instead of claiming it is done.
            # A real LLM pass starts at 'enriched'; human PATCHes move it to
            # 'reviewed'/'final'.
            if source.get("enrichment") in ("heuristic", "heuristic-sensitive"):
                changes["review_state"] = "raw"
            else:
                changes["review_state"] = "enriched"
            note = self.db.update_note(note_id, changes)

            # Fetch existing tasks for this note to preserve state on reprocessing
            existing_rows = self.db.execute(
                "SELECT * FROM tasks WHERE note_id = :nid", {"nid": note_id}
            ).fetchall()
            existing_tasks = [dict(r) for r in existing_rows]
            by_id = {t["id"]: t for t in existing_tasks if t.get("id")}
            by_norm_text: dict[str, list[dict]] = {}
            for t in existing_tasks:
                key = (t.get("text") or "").strip().lower()
                if key:
                    by_norm_text.setdefault(key, []).append(t)

            matched_ids = set()
            new_tasks = []
            default_repo = source.get("repo")
            for item in enriched.get("action_items") or []:
                if isinstance(item, str):
                    item = {"text": item, "priority": "P2", "due_date": None, "repo": None}

                text = (item.get("text") or "").strip()
                norm_text = text.lower()
                item_id = item.get("id")

                match = None
                if item_id and item_id in by_id and item_id not in matched_ids:
                    match = by_id[item_id]
                elif norm_text and norm_text in by_norm_text:
                    for candidate in by_norm_text[norm_text]:
                        if candidate["id"] not in matched_ids:
                            match = candidate
                            break

                if match:
                    matched_ids.add(match["id"])
                    new_tasks.append({
                        "id": match["id"],
                        "note_id": note["id"] if note else note_id,
                        "text": text or match["text"],
                        "done": bool(match["done"]),
                        "completed_at": match["completed_at"] if match["done"] else None,
                        "created_at": match.get("created_at"),
                        "priority": match.get("priority") or item.get("priority", "P2"),
                        "due_date": item.get("due_date") or match.get("due_date"),
                        "repo": item.get("repo") or match.get("repo") or default_repo,
                    })
                else:
                    new_tasks.append({
                        "id": item.get("id"),
                        "note_id": note["id"] if note else note_id,
                        "text": text,
                        "done": bool(item.get("done", False)),
                        "completed_at": item.get("completed_at"),
                        "created_at": item.get("created_at"),
                        "priority": item.get("priority", "P2"),
                        "due_date": item.get("due_date"),
                        "repo": item.get("repo") or default_repo,
                    })

            self.db.execute("DELETE FROM tasks WHERE note_id = :nid", {"nid": note_id})
            self.db.commit()

            for task_data in new_tasks:
                self.db.insert_task(task_data)

            self.db._sync_note_action_items(note_id)
            note = self.db.get_note(note_id)

            # 4.5) #272 auto-filing: rules run before the mirror so the vault
            # copy already reflects the filed state.
            if note:
                note, _filed = self.db.apply_filing_rules(note)

            # 4) embedding + vault mirror + notify
            await self._set_stage(note_id, "syncing")
            if note:
                if note.get("sensitive"):
                    # #26: no embedding vectors for sensitive notes — the
                    # configured embedding backend may be a remote provider.
                    # Drop any vector made before the flag was set, or the
                    # note would stay findable in semantic search.
                    self.db.delete_note_embedding(note_id)
                else:
                    try:
                        embed_note(note, self.db, self.cfg)
                    except Exception as exc:
                        log.warning("failed to embed note %s: %s", note_id, exc)
                markdown.sync_note(self.cfg.paths, note)
                self._maybe_notify(note)
                # close out the syncing stage's timing before the final publish
                fresh = self.db.get_note(note_id) or {}
                src = dict(fresh.get("source") or {})
                anchor = src.get("stage_started_at")
                if anchor and src.get("stage") == "syncing":
                    try:
                        t = dict(src.get("timings") or {})
                        t["syncing"] = round(
                            (datetime.now(timezone.utc) - datetime.fromisoformat(anchor)).total_seconds(), 1
                        )
                        self._patch_source(note_id, {"timings": t})
                    except (ValueError, TypeError):
                        pass
            log.info("note %s processed in %.1fs", note_id, time.monotonic() - started)
            note = self.db.get_note(note_id)
            self.bus.publish("note.updated", note)
        except (TranscriptionError, YouTubeError) as exc:
            self._fail(note_id, str(exc))
        except Exception as exc:
            log.exception("processing note %s failed", note_id)
            self._fail(note_id, f"{type(exc).__name__}: {exc}")

    def _patch_source(self, note_id: str, patch: dict) -> dict:
        """Merge `patch` into source without dropping keys another step wrote."""
        note = self.db.get_note(note_id)
        src = dict((note or {}).get("source") or {})
        src.update(patch)
        self.db.update_note(note_id, {"source": src})
        return src

    async def _set_stage(self, note_id: str, stage: str) -> None:
        note = self.db.get_note(note_id)
        if note:
            source = dict(note.get("source") or {})
            timings = dict(source.get("timings") or {})
            prev = source.get("stage")
            # #323: accumulate per-stage wall-clock seconds so the UI can
            # render the stepper with timings.
            anchor = source.get("stage_started_at")
            if prev and anchor:
                try:
                    started = datetime.fromisoformat(anchor)
                    timings[prev] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
                except (ValueError, TypeError):
                    pass
            elif not prev:
                # First real stage closes out the queue wait.
                try:
                    created = datetime.fromisoformat(note["created_at"])
                    timings["queued"] = round((datetime.now(timezone.utc) - created).total_seconds(), 1)
                except (ValueError, TypeError, KeyError):
                    pass
            source["timings"] = timings
            source["stage"] = stage
            source["stage_started_at"] = now_iso()
            note = self.db.update_note(note_id, {"source": source})
            self.bus.publish("note.updated", note)

    def _maybe_notify(self, note: dict) -> None:
        if not self.cfg.notifications.desktop:
            return
        from .notify import send

        title = note.get("title") or "Capture processed"
        body = (note.get("summary") or "ready")[:120]
        send("Fleeting", f"{title} — {body}")
