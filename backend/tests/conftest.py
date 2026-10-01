"""Shared fixtures: isolated DB/config/vault per test, LLM disabled."""

from __future__ import annotations

import pytest

import fleeting.config as fcfg


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with isolated DB, config file and vault; LLM off."""
    monkeypatch.setattr(fcfg, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")

    cfg = fcfg.Config()
    cfg.llm.provider = "none"  # force heuristic path — no network
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.paths.vault_sync = True
    cfg.activity.enabled = False  # keep tests deterministic; collector tested separately

    from fastapi.testclient import TestClient

    from fleeting.main import create_app

    app = create_app(cfg, load_from_disk=False)
    with TestClient(app) as c:
        yield c


def wait_done(client, note_id: str, timeout: float = 10.0) -> dict:
    """Poll until the background worker finishes the note."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        note = client.get(f"/api/notes/{note_id}").json()
        if note["status"] in ("done", "failed"):
            return note
        time.sleep(0.1)
    raise AssertionError("note never finished processing")
