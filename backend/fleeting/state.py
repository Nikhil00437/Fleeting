"""App state shared across routers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .config import Config
from .db import Database
from .events import EventBus
from .process import Processor
from .services.transcribe import Transcriber


@dataclass
class AppState:
    cfg: Config
    db: Database
    bus: EventBus
    transcriber: Transcriber
    processor: Processor
    started_at: float = field(default_factory=lambda: 0.0)
    activity: object = None  # ActivityCollector, set in create_app
    vault_watcher: object = None  # VaultWatcher, set in create_app
    digest_lock: asyncio.Lock | None = None
    # Bearer token for mutating /api requests; None/"" disables the check.
    api_token: str | None = None

    def cfg_audio_dir(self):
        from .config import AUDIO_DIR, ensure_dirs

        ensure_dirs()
        return AUDIO_DIR
