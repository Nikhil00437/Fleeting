"""Vault watcher and echo suppression engine for Markdown sync."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

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
    ) -> None:
        self.vault_dir = Path(vault_dir)
        self.on_change = on_change
        self.debounce_secs = debounce_secs
        self._observer: Observer | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _should_ignore(self, path: Path) -> bool:
        """Ignore directory events, dotfiles, non-markdown files, and temp files."""
        name = path.name
        if name.startswith("."):
            return True
        if not name.endswith(".md"):
            return True
        if name.endswith(".tmp") or name.endswith(".swp") or name.endswith("~"):
            return True
        try:
            rel = path.resolve().relative_to(self.vault_dir.resolve())
            if any(part.startswith(".") for part in rel.parts):
                return True
        except ValueError:
            pass
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
        return self._observer is not None and self._observer.is_alive()
