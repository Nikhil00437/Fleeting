"""#248 weekly small-multiples tests."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.small_multiples import get_weekly_small_multiples


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_sm.db")
    database.migrate()
    return database


def test_small_multiples_empty(db: Database) -> None:
    cfg = Config()
    res = get_weekly_small_multiples(db, cfg, week_start="2026-10-05")
    assert res["week_start"] == "2026-10-05"
    assert res["week_end"] == "2026-10-11"
    assert len(res["days"]) == 7
    assert [d["day_of_week"] for d in res["days"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert res["total_seconds"] == 0
    assert all(len(d["hourly"]) == 24 for d in res["days"])


def test_small_multiples_with_sessions(db: Database) -> None:
    cfg = Config()
    # Wednesday = 2026-10-07
    db.upsert_activity({
        "app_class": "Code",
        "title": "small_multiples.py",
        "project": "Fleeting",
        "day": "2026-10-07",
        "first_seen": "2026-10-07T14:00:00",
        "last_seen": "2026-10-07T16:00:00",
        "seconds": 7200,
        "idle_secs": 0,
    })

    res = get_weekly_small_multiples(db, cfg, week_start="2026-10-05")
    assert res["total_seconds"] == 7200

    wed = res["days"][2]
    assert wed["day"] == "2026-10-07"
    assert wed["day_of_week"] == "Wed"
    assert wed["total_seconds"] == 7200
    assert wed["hourly"][14] == 3600
    assert wed["hourly"][15] == 3600
    assert wed["top_app"] == "Code"
    assert res["max_hourly_seconds"] >= 3600


def test_small_multiples_api(client) -> None:
    resp = client.get("/api/activity/small-multiples?week=2026-10-05")
    assert resp.status_code == 200
    data = resp.json()
    assert "week_start" in data
    assert len(data["days"]) == 7
