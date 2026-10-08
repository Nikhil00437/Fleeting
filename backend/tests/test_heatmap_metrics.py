"""#252 calendar-style heatmap for note creation and task completion."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.metrics import heatmap


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_heat.db")
    database.migrate()
    return database


def test_heatmap_notes_metric(db: Database) -> None:
    # Insert notes across two days
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, created_at, updated_at)"
        " VALUES ('n1', 'text', 'Note 1', 'hello', '2026-10-08 10:00:00', '2026-10-08 10:00:00')"
    )
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, created_at, updated_at)"
        " VALUES ('n2', 'text', 'Note 2', 'world', '2026-10-08 11:00:00', '2026-10-08 11:00:00')"
    )
    db.execute(
        "INSERT INTO notes (id, type, title, raw_text, created_at, updated_at)"
        " VALUES ('n3', 'text', 'Note 3', 'foo', '2026-10-07 09:00:00', '2026-10-07 09:00:00')"
    )

    res = heatmap(db, weeks=2, end="2026-10-08", metric="notes")
    assert res["metric"] == "notes"
    cells = {c["day"]: c["minutes"] for c in res["cells"]}
    assert cells["2026-10-08"] == 2
    assert cells["2026-10-07"] == 1
    assert res["peak_minutes"] == 2


def test_heatmap_tasks_metric(db: Database) -> None:
    note = db.insert_note({"type": "text", "title": "t", "raw_text": "r"})
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, created_at, completed_at)"
        " VALUES ('t1', ?, 'Task 1', 1, '2026-10-08 09:00:00', '2026-10-08 10:00:00')",
        (note["id"],),
    )
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, created_at, completed_at)"
        " VALUES ('t2', ?, 'Task 2', 1, '2026-10-08 09:00:00', '2026-10-08 12:00:00')",
        (note["id"],),
    )
    # Undone task should not appear in tasks completed heatmap
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, created_at)"
        " VALUES ('t3', ?, 'Task 3', 0, '2026-10-08 09:00:00')",
        (note["id"],),
    )

    res = heatmap(db, weeks=2, end="2026-10-08", metric="tasks")
    assert res["metric"] == "tasks"
    cells = {c["day"]: c["minutes"] for c in res["cells"]}
    assert cells["2026-10-08"] == 2


def test_heatmap_api_metrics(client) -> None:
    resp = client.get("/api/activity/metrics/heatmap?weeks=2&metric=notes")
    assert resp.status_code == 200
    assert resp.json()["metric"] == "notes"

    resp2 = client.get("/api/activity/metrics/heatmap?weeks=2&metric=tasks")
    assert resp2.status_code == 200
    assert resp2.json()["metric"] == "tasks"
