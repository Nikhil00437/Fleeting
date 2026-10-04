"""Activity retention must actually run at boot.

The `activity` table grew without bound: nothing ever deleted from it, and a row
is written on every window-title change. Pruning exists now, so it has to happen
on startup — otherwise the method exists and nothing calls it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import fleeting.config as fcfg
from fleeting.db import Database


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A DB with old + recent activity, wired into an app instance."""
    from fastapi.testclient import TestClient

    path = tmp_path / "ret.db"
    db = Database(path)
    db.migrate()

    old_day = (datetime.now().astimezone() - timedelta(days=90)).strftime("%Y-%m-%d")
    new_day = datetime.now().astimezone().strftime("%Y-%m-%d")
    for i in range(5):
        db.upsert_activity(
            {
                "app_class": f"old{i}",
                "title": "t",
                "first_seen": f"{old_day}T10:00:00+00:00",
                "last_seen": f"{old_day}T10:05:00+00:00",
                "seconds": 300,
                "day": old_day,
            }
        )
    db.upsert_activity(
        {
            "app_class": "recent",
            "title": "t",
            "first_seen": f"{new_day}T10:00:00+00:00",
            "last_seen": f"{new_day}T10:05:00+00:00",
            "seconds": 300,
            "day": new_day,
        }
    )

    monkeypatch.setattr(fcfg, "DB_PATH", path)
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    monkeypatch.setattr(fcfg, "CONFIG_DIR", tmp_path)

    cfg = fcfg.Config()
    cfg.llm.provider = "none"
    cfg.activity.enabled = False
    cfg.activity.retention_days = 30
    cfg.paths.vault_dir = str(tmp_path / "vault")
    return db, cfg, TestClient


def _app_client(db, cfg, TestClient):
    from fleeting.main import create_app

    # Real base_url: the app validates the Host header (DNS-rebinding guard),
    # and TestClient's default "testserver" is not a legitimate host.
    return TestClient(
        create_app(cfg, load_from_disk=False), base_url=f"http://127.0.0.1:{cfg.server.port}"
    )


def test_boot_prunes_rows_beyond_retention(seeded) -> None:
    db, cfg, TestClient = seeded
    assert db.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"] == 6

    with _app_client(db, cfg, TestClient):
        pass

    apps = {r["app_class"] for r in db.known_apps()}
    assert "recent" in apps, "recent activity was pruned"
    assert not any(a.startswith("old") for a in apps), "old activity was not pruned"


def test_retention_window_is_configurable(seeded, tmp_path, monkeypatch) -> None:
    """A longer retention must keep more history."""
    from fastapi.testclient import TestClient

    db, cfg, _ = seeded
    cfg.activity.retention_days = 365

    with _app_client(db, cfg, TestClient):
        pass

    apps = {r["app_class"] for r in db.known_apps()}
    assert any(a.startswith("old") for a in apps), "365-day retention pruned 90-day-old rows"


def test_a_failed_prune_does_not_stop_startup(seeded, monkeypatch) -> None:
    """Retention is housekeeping; it must never prevent the app booting."""
    from fastapi.testclient import TestClient

    db, cfg, _ = seeded

    def boom(*a, **kw):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(Database, "prune_activity", boom)

    with _app_client(db, cfg, TestClient) as c:
        assert c.get("/api/health").status_code == 200


def test_retention_days_is_validated(seeded) -> None:
    """A nonsense value must not delete everything or crash."""
    from fastapi.testclient import TestClient

    db, cfg, _ = seeded
    cfg.activity.retention_days = 0  # clamped to >= 1

    with _app_client(db, cfg, TestClient):
        pass

    assert db.execute("SELECT COUNT(*) AS c FROM activity").fetchone()["c"] >= 1


def test_retention_setting_round_trips(client) -> None:
    client.put("/api/settings", json={"activity_retention_days": 7})
    assert client.get("/api/settings").json()["activity_retention_days"] == 7