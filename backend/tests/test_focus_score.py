"""#57 daily focus score, shown as a trend."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.metrics import daily_focus_score, focus_score_trend


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_focus.db")
    database.migrate()
    return database


def test_focus_score_zero_activity(db: Database) -> None:
    res = daily_focus_score(db, "2026-10-08")
    assert res["score"] == 0
    assert res["grade"] == "Rest / Inactive"
    assert res["total_seconds"] == 0


def test_focus_score_calculation(db: Database) -> None:
    # 4 hours (14400s) of focused work on project 'fleeting' with 4 long sessions
    # first session: 3600s
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'nvim', '2026-10-08T09:00:00', '2026-10-08T10:00:00', 3600, '2026-10-08', 'fleeting')"
    )
    # second session: 3600s
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'nvim', '2026-10-08T10:05:00', '2026-10-08T11:05:00', 3600, '2026-10-08', 'fleeting')"
    )
    # third session: 3600s
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'test', '2026-10-08T11:10:00', '2026-10-08T12:10:00', 3600, '2026-10-08', 'fleeting')"
    )
    # fourth session: 3600s
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'doc', '2026-10-08T13:00:00', '2026-10-08T14:00:00', 3600, '2026-10-08', 'fleeting')"
    )

    res = daily_focus_score(db, "2026-10-08")
    # 4 hours full duration (40 pts) + high stretch avg (35 pts) + 100% project time (25 pts) = 100
    assert res["score"] >= 90
    assert res["grade"] == "Deep Focus"
    assert res["total_seconds"] == 14400
    assert res["components"]["duration"] == 40.0
    assert res["components"]["project"] == 25.0


def test_focus_score_fragmented_day(db: Database) -> None:
    # 10 quick 1-minute sessions with alternating apps (high context switching)
    for i in range(10):
        app = "slack" if i % 2 == 0 else "browser"
        start = f"2026-10-08T10:{i:02d}:00"
        end = f"2026-10-08T10:{i:02d}:50"
        db.execute(
            "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
            " VALUES (?, 'chat', ?, ?, 60, '2026-10-08', NULL)",
            (app, start, end),
        )

    res = daily_focus_score(db, "2026-10-08")
    # Low time (600s = 10 min), high switching rate, no project time -> low score
    assert res["score"] < 40
    assert res["grade"] in ("Scattered", "Moderate")


def test_focus_score_trend(db: Database) -> None:
    # Seed 3 days
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'a', '2026-10-06T10:00:00', '2026-10-06T12:00:00', 7200, '2026-10-06', 'fleeting')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'b', '2026-10-07T10:00:00', '2026-10-07T13:00:00', 10800, '2026-10-07', 'fleeting')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('ghostty', 'c', '2026-10-08T10:00:00', '2026-10-08T14:00:00', 14400, '2026-10-08', 'fleeting')"
    )

    trend = focus_score_trend(db, days=7, end_day="2026-10-08")
    assert len(trend["days"]) == 7
    assert trend["average_score"] > 0
    assert trend["active_days_count"] == 3
    # last day is highest
    assert trend["days"][-1]["score"] >= trend["days"][-2]["score"]


def test_focus_score_api(client) -> None:
    resp = client.get("/api/activity/focus-score?day=2026-10-08")
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "grade" in data

    resp_trend = client.get("/api/activity/focus-score/trend?days=7")
    assert resp_trend.status_code == 200
    data_trend = resp_trend.json()
    assert "days" in data_trend
    assert "average_score" in data_trend
