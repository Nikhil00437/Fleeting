"""#250 task funnel: captured, planned, started, completed."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.task_funnel import get_task_funnel


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_funnel.db")
    database.migrate()
    return database


def test_task_funnel_empty(db: Database) -> None:
    res = get_task_funnel(db)
    assert len(res["stages"]) == 4
    for stage in res["stages"]:
        assert stage["count"] == 0
        assert stage["pct_of_captured"] == 0.0


def test_task_funnel_stages(db: Database) -> None:
    note = db.insert_note({"type": "text", "title": "t", "raw_text": "r"})

    # 1. Captured only (no due date, no estimate, no spent, undone, inbox)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, list)"
        " VALUES ('t1', ?, 'Just captured', 0, 'P2', '2026-10-08T09:00:00Z', 'inbox')",
        (note["id"],),
    )

    # 2. Planned (has due_date, no spent, undone)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, due_date, list)"
        " VALUES ('t2', ?, 'Planned task', 0, 'P1', '2026-10-08T09:00:00Z', '2026-10-09', 'inbox')",
        (note["id"],),
    )

    # 3. Started (has spent_min > 0, undone)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, estimate_min, spent_min, list)"
        " VALUES ('t3', ?, 'Started task', 0, 'P1', '2026-10-08T09:00:00Z', 60, 30, 'inbox')",
        (note["id"],),
    )

    # 4. Completed (done = 1)
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, created_at, due_date, spent_min, completed_at, list)"
        " VALUES ('t4', ?, 'Done task', 1, 'P1', '2026-10-08T09:00:00Z', '2026-10-08', 45, '2026-10-08T10:00:00Z', 'inbox')",
        (note["id"],),
    )

    res = get_task_funnel(db)
    stages = {s["stage"]: s for s in res["stages"]}

    # All 4 were captured
    assert stages["captured"]["count"] == 4
    assert stages["captured"]["pct_of_captured"] == 100.0

    # t2, t3, t4 are planned (t2 has due_date, t3 has estimate_min, t4 has due_date & is completed)
    assert stages["planned"]["count"] == 3
    assert stages["planned"]["pct_of_captured"] == 75.0

    # t3 (spent > 0) and t4 (done = 1) are started
    assert stages["started"]["count"] == 2
    assert stages["started"]["pct_of_captured"] == 50.0

    # t4 is completed
    assert stages["completed"]["count"] == 1
    assert stages["completed"]["pct_of_captured"] == 25.0

    # Priority breakdown
    assert "P1" in res["by_priority"]
    assert res["by_priority"]["P1"]["captured"] == 3
    assert res["by_priority"]["P1"]["completed"] == 1


def test_task_funnel_api(client) -> None:
    resp = client.get("/api/tasks/funnel")
    assert resp.status_code == 200
    data = resp.json()
    assert "stages" in data
    assert len(data["stages"]) == 4
