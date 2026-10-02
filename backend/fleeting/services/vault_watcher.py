"""Vault watcher and echo suppression engine for Markdown sync."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from ..db import _row_to_task, now_iso
from .embeddings import embed_note

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database
    from ..events import EventBus

log = logging.getLogger("fleeting.vault_watcher")


class VaultSyncRegistry:
    """Thread-safe registry tracking SHA-256 hashes of Fleeting-written files.

    Used to detect and suppress echo events triggered by Fleeting's own disk writes.
    """

    def __init__(self) -> None:
        self._hashes: dict[str, tuple[str, float]] = {}  # abs_path -> (sha256, monotonic_time)
        self._lock = threading.Lock()

    def register(self, path: Path | str, content: str) -> str:
        """Register the SHA-256 hash and timestamp of a written file.

        Returns the 64-character hexadecimal SHA-256 digest.
        """
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = str(Path(path).resolve())
        with self._lock:
            # Prune stale entries if dict grows large
            if len(self._hashes) > 1000:
                now = time.monotonic()
                self._hashes = {k: v for k, v in self._hashes.items() if (now - v[1]) <= 60.0}
            self._hashes[key] = (h, time.monotonic())
        return h

    def is_echo(self, path: Path | str, content: str, ttl: float = 10.0) -> bool:
        """Check if content matches the registered hash within the TTL window."""
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = str(Path(path).resolve())
        with self._lock:
            entry = self._hashes.get(key)
            if not entry:
                return False
            reg_hash, reg_time = entry
            if reg_hash == h and (time.monotonic() - reg_time) <= ttl:
                return True
            return False

    def clear(self) -> None:
        """Clear all registered hashes."""
        with self._lock:
            self._hashes.clear()


# Global singleton instance for vault synchronization
sync_registry = VaultSyncRegistry()


class _VaultEventHandler(FileSystemEventHandler):
    """Internal watchdog event handler dispatching to VaultWatcher."""

    def __init__(self, watcher: VaultWatcher) -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher._handle_raw_event(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher._handle_raw_event(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src = getattr(event, "src_path", None)
            if src:
                self.watcher._handle_raw_event(src)
            dest = getattr(event, "dest_path", None)
            if dest:
                self.watcher._handle_raw_event(dest)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher._handle_raw_event(event.src_path)


class VaultWatcher:
    """Watches the vault directory using watchdog and debounces file events."""

    def __init__(
        self,
        vault_dir: Path | str,
        on_change: Callable[[Path], Any] | None = None,
        debounce_secs: float = 0.4,
        db: Database | None = None,
        bus: EventBus | None = None,
        cfg: Config | None = None,
    ) -> None:
        self.vault_dir = Path(os.path.expanduser(str(vault_dir)))
        self.db = db
        self.bus = bus
        self.cfg = cfg
        if on_change is None and db is not None and bus is not None and cfg is not None:
            self.on_change = self.handle_file_change
        else:
            self.on_change = on_change
        self.debounce_secs = debounce_secs
        self._observer: Observer | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    def handle_file_change(self, path: Path) -> dict | None:
        """Handle a file change event using configured db, bus, and cfg."""
        if self.db is not None and self.bus is not None and self.cfg is not None:
            return sync_file_change(path, self.db, self.bus, self.cfg)
        return None

    def resync_all(self) -> dict:
        """Resync all notes in the vault using configured db, bus, and cfg."""
        if self.db is None or self.bus is None or self.cfg is None:
            raise ValueError("VaultWatcher requires db, bus, and cfg to resync")
        return resync_all(self.vault_dir, self.db, self.bus, self.cfg)

    def _should_ignore(self, path: Path) -> bool:
        """Ignore directory events, dotfiles, non-markdown files, temp files, and external paths."""
        name = path.name
        if name.startswith(".") or name.startswith("#"):
            return True
        if not name.endswith(".md"):
            return True
        if name.endswith(".tmp.md") or ".tmp." in name:
            return True
        try:
            rel = path.resolve().relative_to(self.vault_dir.resolve())
            if any(part.startswith(".") for part in rel.parts):
                return True
        except ValueError:
            # Path is outside vault_dir
            return True
        return False

    def _handle_raw_event(self, path_str: str) -> None:
        p = Path(path_str)
        if self._should_ignore(p):
            return
        self._schedule_debounce(p)

    def _schedule_debounce(self, path: Path) -> None:
        key = str(path.resolve())
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()

            def _fire(target: Path = path, k: str = key) -> None:
                with self._lock:
                    self._timers.pop(k, None)
                if self.on_change is not None:
                    try:
                        self.on_change(target)
                    except Exception:
                        log.exception("Error in vault watcher on_change callback for %s", target)

            timer = threading.Timer(self.debounce_secs, _fire)
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def start(self) -> None:
        """Start observer if vault directory exists."""
        with self._lock:
            if self.is_running():
                return
            if not self.vault_dir.exists() or not self.vault_dir.is_dir():
                log.warning("Vault directory does not exist or is not a directory: %s", self.vault_dir)
                return

            handler = _VaultEventHandler(self)
            obs = Observer()
            obs.schedule(handler, str(self.vault_dir.resolve()), recursive=True)
            obs.daemon = True
            obs.start()
            self._observer = obs
            log.info("Vault watcher started for %s", self.vault_dir)

    def stop(self) -> None:
        """Stop observer and cancel pending debounce timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

            if self._observer is not None:
                if self._observer.is_alive():
                    self._observer.stop()
                    self._observer.join(timeout=2.0)
                self._observer = None
                log.info("Vault watcher stopped for %s", self.vault_dir)

    def is_running(self) -> bool:
        """Return True if observer is active and running."""
        with self._lock:
            return self._observer is not None and self._observer.is_alive()


def sync_file_change(
    path: Path | str,
    db: Database,
    bus: EventBus,
    cfg: Config,
) -> dict | None:
    """Ingest a vault file change into SQLite and broadcast events.

    Returns:
        dict describing the action taken (e.g. {"action": "updated", "note_id": note_id}),
        or None if no action or suppressed echo.
    """
    from .markdown import parse_note_md, render_note_md

    path = Path(path)

    # 1. Deletion / non-existence handling
    if not path.exists():
        m = re.search(r"fleeting-([a-zA-Z0-9_-]+)\.md$", path.name)
        if not m:
            return None
        note_id = m.group(1)
        note = db.get_note(note_id)
        if note and not note.get("archived"):
            updated_note = db.update_note(note_id, {"archived": True})
            bus.publish("note.updated", updated_note or note)
            return {"action": "archived", "note_id": note_id}
        return None

    # Filter out hidden or non-markdown files
    name = path.name
    if name.startswith(".") or name.startswith("#") or not name.endswith(".md") or name.endswith(".tmp.md") or ".tmp." in name:
        return None

    # 2. Read content
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Could not read vault file %s: %s", path, exc)
        return None

    # 3. Echo suppression
    if sync_registry.is_echo(path, content):
        return None

    # 4. Parse content
    parsed = parse_note_md(content)

    note_id = parsed.get("id")
    existing_note = db.get_note(note_id) if note_id else None

    # 5. Branch A: Existing note in DB
    if note_id and existing_note:
        changes: dict[str, Any] = {}
        if parsed.get("title") and parsed["title"] != existing_note.get("title"):
            changes["title"] = parsed["title"]
        if parsed.get("tags") is not None and parsed["tags"] != (existing_note.get("tags") or []):
            changes["tags"] = parsed["tags"]
        if parsed.get("summary") is not None and parsed["summary"] != (existing_note.get("summary") or ""):
            changes["summary"] = parsed["summary"]
        if parsed.get("raw_text") is not None and parsed["raw_text"] != (existing_note.get("raw_text") or ""):
            changes["raw_text"] = parsed["raw_text"]

        # Reconcile tasks
        raw_tasks = db.execute("SELECT * FROM tasks WHERE note_id = ?", (note_id,)).fetchall()
        existing_tasks = [_row_to_task(r) for r in raw_tasks]

        parsed_items = parsed.get("action_items") or []
        remaining_existing = {t["id"]: t for t in existing_tasks}
        matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        new_items: list[dict[str, Any]] = []

        # Match by ID if present
        for it in parsed_items:
            it_id = it.get("id")
            if it_id and it_id in remaining_existing:
                matched_pairs.append((it, remaining_existing.pop(it_id)))
            elif it_id and f"{note_id}_{it_id}" in remaining_existing:
                matched_pairs.append((it, remaining_existing.pop(f"{note_id}_{it_id}")))

        # Match remaining by normalized text
        unmatched_parsed = [it for it in parsed_items if not any(it is p[0] for p in matched_pairs)]
        for it in unmatched_parsed:
            norm_text = it.get("text", "").strip().lower()
            found_id = None
            for ex_id, ex_t in remaining_existing.items():
                if ex_t.get("text", "").strip().lower() == norm_text:
                    found_id = ex_id
                    matched_pairs.append((it, ex_t))
                    break
            if found_id:
                remaining_existing.pop(found_id)
            else:
                new_items.append(it)

        tasks_modified_count = 0

        # Existing tasks missing from markdown checklist -> delete
        for del_id in list(remaining_existing.keys()):
            db.delete_task(del_id)
            bus.publish("task.deleted", {"id": del_id, "note_id": note_id})
            tasks_modified_count += 1

        # Update matched tasks
        for it, ex_t in matched_pairs:
            t_changes: dict[str, Any] = {}
            if it.get("text") and it["text"] != ex_t["text"]:
                t_changes["text"] = it["text"]
            if bool(it.get("done")) != bool(ex_t["done"]):
                t_changes["done"] = bool(it.get("done"))
                t_changes["completed_at"] = now_iso() if it.get("done") else None
            if it.get("priority") and it["priority"] != ex_t.get("priority"):
                t_changes["priority"] = it["priority"]
            if "due_date" in it and it.get("due_date") != ex_t.get("due_date"):
                t_changes["due_date"] = it.get("due_date")
            if "repo" in it and it.get("repo") != ex_t.get("repo"):
                t_changes["repo"] = it.get("repo")

            if t_changes:
                upd = db.update_task(ex_t["id"], t_changes)
                if upd:
                    bus.publish("task.updated", upd)
                    tasks_modified_count += 1

        # Insert new tasks
        for it in new_items:
            inserted = db.insert_task({
                "id": it.get("id"),
                "note_id": note_id,
                "text": it.get("text", ""),
                "done": it.get("done", False),
                "priority": it.get("priority", "P2"),
                "due_date": it.get("due_date"),
                "repo": it.get("repo"),
            })
            bus.publish("task.created", inserted)
            tasks_modified_count += 1

        tasks_changed = tasks_modified_count > 0

        if not changes and not tasks_changed:
            sync_registry.register(path, content)
            return {"action": "unchanged", "note_id": note_id, "tasks_updated": 0}

        if changes:
            db.update_note(note_id, changes)
        if tasks_changed:
            db._sync_note_action_items(note_id)

        refreshed_note = db.get_note(note_id)
        target_note = refreshed_note or existing_note
        if target_note:
            try:
                embed_note(target_note, db, cfg)
            except Exception as exc:
                log.warning("Failed to embed updated note %s: %s", note_id, exc)
        sync_registry.register(path, content)
        bus.publish("note.updated", target_note)

        return {"action": "updated", "note_id": note_id, "tasks_updated": tasks_modified_count}

    # 6. Branch B: Untracked / newly created file in vault
    title = parsed.get("title") or path.stem
    new_note_data = {
        "type": parsed.get("type") or "text",
        "title": title,
        "raw_text": parsed.get("raw_text") or "",
        "summary": parsed.get("summary") or "",
        "tags": parsed.get("tags") or [],
        "status": "done",
    }
    new_note = db.insert_note(new_note_data)
    created_note_id = new_note["id"]

    tasks_count = 0
    parsed_items = parsed.get("action_items") or []
    for it in parsed_items:
        t = db.insert_task({
            "id": it.get("id"),
            "note_id": created_note_id,
            "text": it.get("text", ""),
            "done": it.get("done", False),
            "priority": it.get("priority", "P2"),
            "due_date": it.get("due_date"),
            "repo": it.get("repo"),
        })
        bus.publish("task.created", t)
        tasks_count += 1

    if parsed_items:
        db._sync_note_action_items(created_note_id)

    refreshed_new_note = db.get_note(created_note_id) or new_note
    try:
        embed_note(refreshed_new_note, db, cfg)
    except Exception as exc:
        log.warning("Failed to embed created note %s: %s", created_note_id, exc)
    rendered = render_note_md(refreshed_new_note)

    # Register hash first, then write updated content with id frontmatter back to disk
    sync_registry.register(path, rendered)
    try:
        path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        log.error("Failed to write frontmatter back to new vault note %s: %s", path, exc)

    bus.publish("note.created", refreshed_new_note)
    return {"action": "created", "note_id": created_note_id, "tasks_updated": tasks_count}


def resync_all(
    vault_dir: Path | str,
    db: Database,
    bus: EventBus,
    cfg: Config,
) -> dict:
    """Traverses vault_dir, reconciles all .md files, and exports missing active notes."""
    from .markdown import sync_note, vault_path_for

    v_dir = Path(os.path.expanduser(str(vault_dir))).resolve()
    try:
        v_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    if not v_dir.exists() or not v_dir.is_dir():
        log.warning("Vault directory does not exist for resync: %s", v_dir)
        return {"ok": False, "synced_notes": 0, "imported_notes": 0, "tasks_updated": 0}

    synced_notes = 0
    imported_notes = 0
    tasks_updated = 0
    seen_note_ids: set[str] = set()

    # 1. Traverse vault_dir recursively for .md files
    md_files = sorted(v_dir.rglob("*.md"))
    for file_path in md_files:
        name = file_path.name
        if name.startswith(".") or name.startswith("#") or name.endswith(".tmp.md") or ".tmp." in name:
            continue
        try:
            rel = file_path.relative_to(v_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
        except ValueError:
            continue

        # Extract frontmatter id if already present or from filename
        try:
            content_preview = file_path.read_text(encoding="utf-8", errors="ignore")[:4096]
            fm_id = re.search(r"^id:\s*['\"]?([a-zA-Z0-9_-]+)['\"]?", content_preview, re.MULTILINE)
            if fm_id:
                seen_note_ids.add(fm_id.group(1).strip())
        except Exception:
            pass

        m = re.search(r"fleeting-([a-zA-Z0-9_-]+)\.md$", name)
        if m:
            seen_note_ids.add(m.group(1))

        try:
            res = sync_file_change(file_path, db, bus, cfg)
            if res:
                nid = res.get("note_id")
                if nid:
                    seen_note_ids.add(str(nid))
                action = res.get("action")
                if action == "created":
                    imported_notes += 1
                elif action == "updated":
                    synced_notes += 1
                tasks_updated += res.get("tasks_updated", 0)
        except Exception as exc:
            log.exception("Error syncing file %s: %s", file_path, exc)
            continue

    # 2. Export active DB notes not currently on disk
    active_notes = db.list_notes(archived=False, limit=10000)
    for note in active_notes:
        note_id = str(note.get("id") or "")
        if note_id in seen_note_ids:
            continue
        expected_path = vault_path_for(cfg.paths, note)
        if not expected_path.exists() and note_id not in seen_note_ids:
            out_path = sync_note(cfg.paths, note)
            if out_path:
                synced_notes += 1

    return {
        "ok": True,
        "synced_notes": synced_notes,
        "imported_notes": imported_notes,
        "tasks_updated": tasks_updated,
    }
