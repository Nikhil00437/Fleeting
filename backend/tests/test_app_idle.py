"""#340 per-app idle thresholds."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fleeting.activity import ActivityCollector, idle_minutes_for
from fleeting.config import ActivityConfig

NOW = datetime(2026, 10, 8, 9, 0, 0)


class FakeDB:
    def __init__(self):
        self.rows: list[dict] = []
        self.store: dict[str, str] = {}
        self.idle_rules: dict[str, int] = {}

    def upsert_activity(self, row):
        if row.get("id") is not None:
            self.rows[row["id"]] = dict(row)
            return row["id"]
        r = dict(row)
        r["id"] = len(self.rows)
        self.rows.append(r)
        return r["id"]

    def activity_sessions(self, day):
        return [dict(r) for r in self.rows if r.get("day") == day and r.get("seconds", 0) >= 1]

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value

    def app_rules(self):
        return {}

    def app_aliases(self):
        return {}

    def app_idle_rules(self) -> dict[str, int]:
        return dict(self.idle_rules)

    def set_app_idle_rule(self, app_class: str, minutes: int | None) -> None:
        if minutes is None:
            self.idle_rules.pop(app_class, None)
        else:
            self.idle_rules[app_class] = minutes


@pytest.fixture
def db(tmp_path: Path):
    from fleeting.db import Database

    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _collector(db=None, **cfg_kwargs) -> tuple[ActivityCollector, FakeDB]:
    fake = db if isinstance(db, FakeDB) else FakeDB()
    cfg_kwargs.setdefault("idle_after_min", 3)
    cfg = ActivityConfig(poll_secs=20, auto_daily_log=False, **cfg_kwargs)
    return ActivityCollector(fake, cfg, probe=lambda: (None, None)), fake


def test_an_app_without_a_rule_uses_the_global_threshold() -> None:
    col, db = _collector()
    assert idle_minutes_for(col.db, col.cfg, "kitty") == 3


def test_a_per_app_rule_wins() -> None:
    col, db = _collector(idle_after_min=3)
    db.set_app_idle_rule("firefox", 10)
    assert idle_minutes_for(col.db, col.cfg, "firefox") == 10
    assert idle_minutes_for(col.db, col.cfg, "kitty") == 3


def test_idle_time_is_recorded_separately_from_active_time() -> None:
    """The AFK stretch is real time in the session, it just isn't work."""
    col, db = _collector()
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    # cursor never moves: after 3 minutes of polls the session is idle
    for i in range(1, 12):
        col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW + timedelta(seconds=20 * i))
    row = db.rows[0]
    # 11 polls of 20s: the first 8 stretches are active, the last 3 are idle.
    assert row["seconds"] == 160
    assert row["idle_secs"] == 60


def test_a_short_app_threshold_stops_accrual_sooner() -> None:
    col, db = _collector()
    db.set_app_idle_rule("kitty", 1)
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW)
    for i in range(1, 6):
        col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), NOW + timedelta(seconds=20 * i))
    # idle after the 3rd poll (60s >= 1min), so only the first stretch counts
    assert db.rows[0]["seconds"] == 40


def test_idle_rules_round_trip_in_the_database(db) -> None:
    db.set_app_idle_rule("firefox", 7)
    assert db.app_idle_rules() == {"firefox": 7}
    db.set_app_idle_rule("firefox", None)
    assert db.app_idle_rules() == {}


def test_idle_threshold_endpoint(client) -> None:
    client.post("/api/activity/apps/idle", json={"app_class": "firefox", "idle_min": 8})
    assert client.get("/api/activity/apps/idle").json() == [{"app_class": "firefox", "idle_min": 8}]
    assert client.delete("/api/activity/apps/idle/firefox").status_code == 204
    assert client.get("/api/activity/apps/idle").json() == []
    assert client.delete("/api/activity/apps/idle/nothing-here").status_code == 404


def test_the_known_apps_payload_carries_the_threshold(client) -> None:
    client.post("/api/notes", json={"type": "text", "title": "x", "raw_text": "y"})
    client.post("/api/activity/apps/idle", json={"app_class": "firefox", "idle_min": 8})
    rows = client.get("/api/activity/apps").json()
    idle = {r["app_class"]: r.get("idle_min") for r in rows}
    assert idle.get("firefox") == 8