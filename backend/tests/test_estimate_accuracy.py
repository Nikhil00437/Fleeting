"""#170 time-estimate accuracy: predicted vs. actual time on tasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.estimate_accuracy import calculate_estimate_accuracy


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_est.db")
    database.migrate()
    return database


def test_estimate_accuracy_empty(db: Database) -> None:
    res = calculate_estimate_accuracy(db)
    assert res["total_evaluated"] == 0
    assert res["overall_accuracy_pct"] == 0.0
    assert res["bias"] == "no_data"
    assert res["items"] == []


def test_estimate_accuracy_calculation(db: Database) -> None:
    note = db.insert_note({"type": "text", "title": "Tasks", "raw_text": "work"})

    # Task 1: predicted 60m, actual 60m -> perfectly accurate
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, estimate_min, spent_min)"
        " VALUES ('t1', ?, 'Task 1', 1, 'P1', '2026-10-08T09:00:00Z', 60, 60)",
        (note["id"],),
    )

    # Task 2: predicted 30m, actual 60m -> underestimated (took 2x as long)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, estimate_min, spent_min)"
        " VALUES ('t2', ?, 'Task 2', 1, 'P2', '2026-10-08T09:00:00Z', 30, 60)",
        (note["id"],),
    )

    # Task 3: predicted 120m, actual 60m -> overestimated (took half the time)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, estimate_min, spent_min)"
        " VALUES ('t3', ?, 'Task 3', 1, 'P1', '2026-10-08T09:00:00Z', 120, 60)",
        (note["id"],),
    )

    # Task 4: has estimate but no spent_min -> should be counted in untracked_count
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, estimate_min)"
        " VALUES ('t4', ?, 'Task 4', 0, 'P3', '2026-10-08T09:00:00Z', 45)",
        (note["id"],),
    )

    res = calculate_estimate_accuracy(db)
    assert res["total_evaluated"] == 3
    assert res["untracked_count"] == 1
    assert res["total_estimated_min"] == 210  # 60 + 30 + 120
    assert res["total_spent_min"] == 180      # 60 + 60 + 60

    # Counts
    assert res["counts"]["on_target"] == 1       # t1
    assert res["counts"]["underestimated"] == 1   # t2
    assert res["counts"]["overestimated"] == 1    # t3

    # Breakdown by priority
    assert "P1" in res["by_priority"]
    assert res["by_priority"]["P1"]["count"] == 2
    assert res["by_priority"]["P1"]["estimated_min"] == 180
    assert res["by_priority"]["P1"]["spent_min"] == 120

    assert "P2" in res["by_priority"]
    assert res["by_priority"]["P2"]["count"] == 1
    assert res["by_priority"]["P2"]["estimated_min"] == 30
    assert res["by_priority"]["P2"]["spent_min"] == 60


def test_estimate_accuracy_api(client) -> None:
    resp = client.get("/api/tasks/estimate-accuracy")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_evaluated" in data
    assert "overall_accuracy_pct" in data
    assert "counts" in data
    assert "items" in data
