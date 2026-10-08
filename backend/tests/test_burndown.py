"""#423 backlog burndown chart for unprocessed items and open tasks."""

from __future__ import annotations

from pathlib import Path
from datetime import timedelta

import pytest

from fleeting.db import Database
from fleeting.services import calendar_svc
from fleeting.services.burndown import get_backlog_burndown


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_burndown.db")
    database.migrate()
    return database


def test_burndown_empty(db: Database) -> None:
    res = get_backlog_burndown(db, days=14)
    assert res["window_days"] == 14
    assert res["current_backlog"] == 0
    assert res["current_open_tasks"] == 0
    assert res["current_pending_captures"] == 0
    assert len(res["series"]) == 14
    assert res["days_to_zero"] == 0.0


def test_burndown_with_tasks_and_notes(db: Database) -> None:
    today_dt = calendar_svc.today()
    d3_ago = (today_dt - timedelta(days=3)).strftime("%Y-%m-%d") + "T10:00:00Z"
    d2_ago = (today_dt - timedelta(days=2)).strftime("%Y-%m-%d") + "T11:00:00Z"
    d1_ago = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d") + "T12:00:00Z"

    # Note 1: created 3 days ago, still pending
    note1 = db.insert_note({"type": "text", "title": "Pending capture", "raw_text": "r"})
    db.execute("UPDATE notes SET status = 'pending', created_at = ? WHERE id = ?", (d3_ago, note1["id"]))

    # Note 2: created 2 days ago, processed 1 day ago
    note2 = db.insert_note({"type": "text", "title": "Processed capture", "raw_text": "r"})
    db.execute(
        "UPDATE notes SET status = 'processed', created_at = ?, updated_at = ? WHERE id = ?",
        (d2_ago, d1_ago, note2["id"]),
    )

    # Task 1: created 2 days ago, completed 1 day ago
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, completed_at, list)"
        " VALUES ('t1', ?, 'Done task', 1, 'P2', ?, ?, 'inbox')",
        (note1["id"], d2_ago, d1_ago),
    )

    # Task 2: created 1 day ago, still open
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, list)"
        " VALUES ('t2', ?, 'Open task', 0, 'P1', ?, 'inbox')",
        (note1["id"], d1_ago),
    )

    res = get_backlog_burndown(db, days=7)
    assert res["current_open_tasks"] == 1
    assert res["current_pending_captures"] == 1
    assert res["current_backlog"] == 2
    assert res["total_added"] == 4
    assert res["total_resolved"] == 2

    series = {s["day"]: s for s in res["series"]}
    day3_str = (today_dt - timedelta(days=3)).strftime("%Y-%m-%d")
    day2_str = (today_dt - timedelta(days=2)).strftime("%Y-%m-%d")
    day1_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    assert series[day3_str]["captures_added"] == 1
    assert series[day2_str]["tasks_added"] == 1
    assert series[day1_str]["tasks_completed"] == 1
    assert series[day1_str]["captures_resolved"] == 1

    # Open backlog at today
    today_str = today_dt.strftime("%Y-%m-%d")
    assert series[today_str]["open_backlog"] == 2


def test_burndown_api(client) -> None:
    resp = client.get("/api/tasks/burndown?days=14")
    assert resp.status_code == 200
    data = resp.json()
    assert "current_backlog" in data
    assert "series" in data
    assert len(data["series"]) == 14
