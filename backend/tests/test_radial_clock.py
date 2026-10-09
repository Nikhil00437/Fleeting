"""#247 24-hour radial day clock tests."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.radial_clock import get_radial_clock


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_radial.db")
    database.migrate()
    return database


def test_radial_clock_empty(db: Database) -> None:
    cfg = Config()
    res = get_radial_clock(db, cfg, "2026-10-08")
    assert res["day"] == "2026-10-08"
    assert res["total_seconds"] == 0
    assert len(res["hourly"]) == 24
    assert len(res["segments"]) == 0


def test_radial_clock_with_sessions(db: Database) -> None:
    cfg = Config()
    # Insert session: 10:00 to 11:30 (5400s) on code editor
    db.upsert_activity({
        "app_class": "Code",
        "title": "fleeting/services/radial_clock.py",
        "project": "Fleeting",
        "day": "2026-10-08",
        "first_seen": "2026-10-08T10:00:00",
        "last_seen": "2026-10-08T11:30:00",
        "seconds": 5400,
        "idle_secs": 0,
    })

    # Insert session: 21:00 to 22:00 (3600s) on browser (night)
    db.upsert_activity({
        "app_class": "Firefox",
        "title": "Documentation",
        "project": "Research",
        "day": "2026-10-08",
        "first_seen": "2026-10-08T21:00:00",
        "last_seen": "2026-10-08T22:00:00",
        "seconds": 3600,
        "idle_secs": 0,
    })

    res = get_radial_clock(db, cfg, "2026-10-08")
    assert res["total_seconds"] == 9000
    assert res["daytime_seconds"] == 5400
    assert res["night_seconds"] == 3600
    assert len(res["segments"]) == 2

    # Verify angles for 10:00:00 (10/24 * 360 = 150 deg)
    seg1 = next(s for s in res["segments"] if s["app_class"] == "Code")
    assert seg1["start_deg"] == 150.0
    # 11:30:00 = 11.5 / 24 * 360 = 172.5 deg
    assert seg1["end_deg"] == 172.5

    # Hourly buckets
    hourly = {h["hour"]: h for h in res["hourly"]}
    assert hourly[10]["seconds"] == 3600
    assert hourly[11]["seconds"] == 1800
    assert hourly[21]["seconds"] == 3600
    assert res["peak_hour"] in (10, 21)

    # Apps and projects
    assert res["apps"][0]["app"] == "Code"
    assert res["projects"][0]["project"] == "Fleeting"


def test_radial_clock_api(client) -> None:
    resp = client.get("/api/activity/radial-clock?day=2026-10-08")
    assert resp.status_code == 200
    data = resp.json()
    assert "hourly" in data
    assert "segments" in data
    assert len(data["hourly"]) == 24
