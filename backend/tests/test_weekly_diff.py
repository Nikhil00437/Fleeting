"""#346: Weekly diff of focus versus last week in plain English."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.db import Database
from fleeting.services.weeklylog import aggregate_week, compute_weekly_diff, fallback_weekly_digest


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "w_diff.db")
    database.migrate()
    return database


def _sessions(db: Database, day: str, app: str, seconds: int) -> None:
    db.upsert_activity(
        {
            "app_class": app,
            "title": "work",
            "first_seen": f"{day}T10:00:00+00:00",
            "last_seen": f"{day}T11:00:00+00:00",
            "seconds": seconds,
            "day": day,
        }
    )


def test_weekly_diff_both_weeks_empty(db: Database) -> None:
    diff = compute_weekly_diff(db, "2026-10-05")
    assert diff["current_seconds"] == 0
    assert diff["previous_seconds"] == 0
    assert diff["delta_seconds"] == 0
    assert diff["delta_pct"] is None
    assert "No tracked activity" in diff["narrative"]


def test_weekly_diff_with_no_previous_week_activity(db: Database) -> None:
    _sessions(db, "2026-10-05", "code", 7200)
    diff = compute_weekly_diff(db, "2026-10-05")
    assert diff["current_seconds"] == 7200
    assert diff["previous_seconds"] == 0
    assert diff["delta_seconds"] == 7200
    assert "Logged 2h" in diff["narrative"]
    assert "no activity tracked last week" in diff["narrative"]


def test_weekly_diff_focus_increased(db: Database) -> None:
    # Previous week: 2026-09-28 -> 10 hours
    _sessions(db, "2026-09-28", "code", 36000)
    # Current week: 2026-10-05 -> 12 hours
    _sessions(db, "2026-10-05", "code", 43200)

    diff = compute_weekly_diff(db, "2026-10-05")
    assert diff["current_seconds"] == 43200
    assert diff["previous_seconds"] == 36000
    assert diff["delta_seconds"] == 7200
    assert diff["delta_pct"] == 20.0
    assert "Focus was up" in diff["narrative"]
    assert "+20%" in diff["narrative"]
    assert "+2h" in diff["narrative"]
    assert "code increased" in diff["narrative"]


def test_weekly_diff_focus_decreased(db: Database) -> None:
    # Previous week: 10 hours
    _sessions(db, "2026-09-28", "code", 36000)
    # Current week: 8 hours
    _sessions(db, "2026-10-05", "code", 28800)

    diff = compute_weekly_diff(db, "2026-10-05")
    assert diff["current_seconds"] == 28800
    assert diff["previous_seconds"] == 36000
    assert diff["delta_seconds"] == -7200
    assert diff["delta_pct"] == -20.0
    assert "Focus was down" in diff["narrative"]
    assert "-20%" in diff["narrative"]
    assert "-2h" in diff["narrative"]


def test_weekly_diff_app_shifts(db: Database) -> None:
    # Previous week: code 5h, firefox 5h
    _sessions(db, "2026-09-28", "code", 18000)
    _sessions(db, "2026-09-28", "firefox", 18000)
    # Current week: code 8h, firefox 2h
    _sessions(db, "2026-10-05", "code", 28800)
    _sessions(db, "2026-10-05", "firefox", 7200)

    diff = compute_weekly_diff(db, "2026-10-05")
    shifts = {s["app_class"]: s["delta_seconds"] for s in diff["app_shifts"]}
    assert shifts["code"] == 10800  # +3h
    assert shifts["firefox"] == -10800  # -3h

    narrative = diff["narrative"]
    assert "code increased by 3h" in narrative
    assert "firefox decreased by 3h" in narrative


def test_fallback_weekly_digest_includes_diff_section(db: Database) -> None:
    _sessions(db, "2026-09-28", "code", 18000)
    _sessions(db, "2026-10-05", "code", 36000)

    agg = aggregate_week(db, "2026-10-05")
    md = fallback_weekly_digest(agg, "2026-10-05")

    assert "## Focus vs. Last Week" in md
    assert "Focus was up" in md
