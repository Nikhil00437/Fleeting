"""#65 private mode: stop tracking for N minutes, from the tray."""

from __future__ import annotations

from datetime import datetime, timedelta

from fleeting.activity import ActivityCollector, private_until
from fleeting.config import ActivityConfig


class FakeDB:
    def __init__(self):
        self.rows: list[dict] = []
        self.store: dict[str, str] = {}

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

    def kv_delete(self, key):
        return self.store.pop(key, None) is not None

    def app_rules(self):
        return {}

    def app_aliases(self):
        return {}

    def app_idle_rules(self):
        return {}


def _collector() -> ActivityCollector:
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False)
    return ActivityCollector(FakeDB(), cfg, probe=lambda: (None, None))


def test_private_mode_pauses_the_collector() -> None:
    col = _collector()
    assert col.is_paused() is False
    col.set_private(minutes=30)
    assert col.is_paused() is True


def test_private_mode_ends_on_its_own() -> None:
    col = _collector()
    col.set_private(minutes=30)
    # pretend the window passed
    col.db.store["activity_private_until"] = (
        datetime.now().astimezone() - timedelta(minutes=1)
    ).isoformat(timespec="seconds")
    assert col.is_paused() is False


def test_ending_private_mode_early() -> None:
    col = _collector()
    col.set_private(minutes=30)
    assert col.clear_private() is True
    assert col.is_paused() is False
    assert col.clear_private() is False  # nothing to clear


def test_a_manual_pause_still_wins_after_private_mode() -> None:
    col = _collector()
    col.set_paused(True)
    col.clear_private()
    assert col.is_paused() is True


def test_private_mode_closes_the_open_session() -> None:
    col = _collector()
    col.poll_once({"class": "kitty", "title": "vim"}, (0, 0), datetime.now().astimezone())
    assert col.current is not None
    col.set_private(minutes=5)
    assert col.current is None


def test_a_corrupt_timestamp_does_not_pause_forever() -> None:
    col = _collector()
    col.db.store["activity_private_until"] = "not a timestamp"
    assert private_until(col.db) is None
    assert col.is_paused() is False


def test_the_private_endpoints(client) -> None:
    body = client.post("/api/activity/private", json={"minutes": 15}).json()
    assert body["active"] is True
    assert body["until"] > datetime.now().astimezone().isoformat()[:16]

    assert client.get("/api/activity/private").json()["active"] is True
    day = client.get("/api/activity/day").json()
    assert day["paused"] is True
    assert day["private_until"]

    assert client.delete("/api/activity/private").status_code == 204
    assert client.get("/api/activity/private").json()["active"] is False
    assert client.delete("/api/activity/private").status_code == 404


def test_a_nonsense_duration_is_refused(client) -> None:
    assert client.post("/api/activity/private", json={"minutes": 0}).status_code == 422
    assert client.post("/api/activity/private", json={"minutes": 99999}).status_code == 422


def test_the_live_endpoint_reports_private_mode(client) -> None:
    client.post("/api/activity/private", json={"minutes": 5})
    live = client.get("/api/activity/live").json()
    assert live["private_until"]