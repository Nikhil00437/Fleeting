"""#335 auto-grouping sessions into work blocks."""

from __future__ import annotations

from datetime import datetime, timedelta

from fleeting.activity import ActivityCollector, aggregate_day
from fleeting.config import ActivityConfig

NOW = datetime(2026, 10, 8, 9, 0, 0)


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

    def app_rules(self):
        return {}

    def app_aliases(self):
        return {}

    def app_idle_rules(self):
        return {}


def _collector(**cfg_kwargs) -> tuple[ActivityCollector, FakeDB]:
    cfg_kwargs.setdefault("block_gap_min", 10)
    cfg = ActivityConfig(poll_secs=20, idle_after_min=3, auto_daily_log=False, **cfg_kwargs)
    db = FakeDB()
    return ActivityCollector(db, cfg, probe=lambda: (None, None)), db


def _work(col, app: str, title: str, start: datetime, minutes: int = 2) -> None:
    """A realistic stretch: the window is seen repeatedly, so time accrues."""
    for i in range(minutes * 3):
        col.poll_once(
            {"class": app, "title": title}, (i + 1, 0), start + timedelta(seconds=20 * i)
        )
    col.poll_once(None, (0, 0), start + timedelta(seconds=20 * minutes * 3))


def test_back_to_back_sessions_share_a_block() -> None:
    col, db = _collector()
    _work(col, "kitty", "fleeting — vim", NOW)
    _work(col, "firefox", "fleeting — docs", NOW + timedelta(minutes=2))
    assert len(db.rows) == 2
    assert db.rows[0]["block_id"] == db.rows[1]["block_id"]


def test_a_long_gap_starts_a_new_block() -> None:
    col, db = _collector()
    _work(col, "kitty", "fleeting — vim", NOW)
    _work(col, "kitty", "fleeting — vim", NOW + timedelta(minutes=45))
    assert db.rows[0]["block_id"] != db.rows[1]["block_id"]


def test_switching_project_starts_a_new_block() -> None:
    col, db = _collector()
    _work(col, "kitty", "fleeting — vim", NOW)
    _work(col, "kitty", "otherproj — vim", NOW + timedelta(minutes=2))
    assert db.rows[0]["block_id"] != db.rows[1]["block_id"]


def test_block_ids_are_unique_per_day() -> None:
    col, db = _collector()
    _work(col, "kitty", "fleeting — vim", NOW)
    _work(col, "kitty", "fleeting — vim", NOW + timedelta(hours=2))
    assert db.rows[0]["block_id"] != db.rows[1]["block_id"]
    assert db.rows[0]["block_id"].startswith("2026-10-08")


def test_aggregate_day_reports_blocks_with_their_span_and_apps() -> None:
    col, db = _collector()
    _work(col, "kitty", "fleeting — vim", NOW)
    _work(col, "firefox", "fleeting — docs", NOW + timedelta(minutes=2))
    _work(col, "kitty", "fleeting — vim", NOW + timedelta(hours=3))

    agg = aggregate_day(db.activity_sessions("2026-10-08"))
    assert len(agg["blocks"]) == 2
    first = agg["blocks"][0]
    assert first["seconds"] > 0
    assert first["project"] == "fleeting"
    assert set(first["apps"]) == {"kitty", "firefox"}
    assert agg["blocks"][1]["start"] > first["end"]


def test_a_day_with_no_sessions_has_no_blocks() -> None:
    assert aggregate_day([])["blocks"] == []


def test_rows_without_a_block_id_do_not_vanish() -> None:
    """Sessions recorded before this feature must still be listed."""
    agg = aggregate_day(
        [
            {"id": 1, "app_class": "kitty", "title": "vim", "first_seen": "2026-10-08T09:00:00",
             "last_seen": "2026-10-08T09:10:00", "seconds": 600, "day": "2026-10-08"},
        ]
    )
    assert len(agg["blocks"]) == 1
    assert agg["blocks"][0]["seconds"] == 600