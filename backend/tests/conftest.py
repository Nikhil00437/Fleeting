"""Shared fixtures: isolated DB/config/vault per test, LLM disabled.

The session-wide redirect in `pytest_configure` is the important part: it runs
before test modules are imported, and `fleeting.main` builds its app at import
time. Without it, merely importing a test module migrates and rewrites the
user's real database — which is how the 0.7 development runs left rows in it.
`test_no_real_writes.py` asserts the redirect actually holds.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import fleeting.config as fcfg

# Paths that point at the user's real data. Captured before anything moves
# them, so tests can prove they are no longer reachable.
REAL_PATHS = ("DB_PATH", "CONFIG_PATH", "AUDIO_DIR", "ATTACHMENTS_DIR", "LOG_PATH", "VAULT_DIR")
_REAL = {name: fcfg.__dict__[name] for name in REAL_PATHS}


def _sandbox() -> Path:
    return Path(fcfg.__dict__["DB_PATH"]).parent

def pytest_configure(config):
    """Redirect every real path before any test module is imported."""
    sandbox = Path(tempfile.mkdtemp(prefix="fleeting-pytest-"))
    for name in REAL_PATHS:
        setattr(fcfg, name, sandbox / Path(fcfg.__dict__[name]).name)
    sandbox.joinpath("fleeting.db").touch()  # a real (empty) db for imports to migrate


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
    # Real base_url, because the app validates the Host header (DNS-rebinding
    # guard). TestClient's default of "testserver" is not a legitimate host.
    with TestClient(app, base_url=f"http://127.0.0.1:{cfg.server.port}") as c:
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
