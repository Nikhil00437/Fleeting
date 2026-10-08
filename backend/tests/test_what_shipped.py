"""#166 Weekly 'what shipped' view combining commits, tasks, and notes."""

from __future__ import annotations

from pathlib import Path
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.what_shipped import get_what_shipped


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "shipped.db")
    database.migrate()
    return database


def test_what_shipped_aggregates_items(db: Database) -> None:
    cfg = Config()
    week_start = "2026-10-05"  # Monday

    # 1. Insert a completed task in that week
    db.insert_task(
        {
            "text": "Build report playground UI",
            "done": True,
            "priority": "P1",
            "repo": "fleeting",
            "created_at": "2026-10-06T10:00:00+00:00",
            "completed_at": "2026-10-07T12:00:00+00:00",
        }
    )

    # 2. Insert a note in that week
    db.insert_note(
        {
            "title": "Weekly Planning Spec",
            "raw_text": "Spec for version 0.8",
            "type": "text",
            "tags": ["v0.8", "spec"],
            "created_at": "2026-10-06T11:00:00+00:00",
        }
    )

    # 3. Insert a commit in that week
    db.execute(
        """INSERT INTO commits (repo, subject, author, committed_at, recorded_at)
        VALUES ('fleeting', 'feat(reports): add report playground', 'Developer', '2026-10-07T15:00:00', '2026-10-07T15:00:00')"""
    )
    db.commit()

    res = get_what_shipped(db, cfg, week_start=week_start)
    assert res["week_start"] == "2026-10-05"
    assert res["counts"]["tasks"] >= 1
    assert res["counts"]["notes"] >= 1
    assert res["counts"]["commits"] >= 1
    assert res["counts"]["total"] >= 3

    # Check markdown format
    md = res["markdown"]
    assert "# What Shipped" in md
    assert "Git Commits" in md
    assert "Completed Tasks" in md
    assert "Build report playground UI" in md
    assert "Weekly Planning Spec" in md


def test_what_shipped_empty_week(db: Database) -> None:
    cfg = Config()
    cfg.activity.watch_dirs = ""
    res = get_what_shipped(db, cfg, week_start="2026-09-01")
    assert res["counts"]["total"] == 0
    assert "No git commits recorded" in res["markdown"]
    assert "No completed tasks recorded" in res["markdown"]


def test_what_shipped_api_endpoints(client) -> None:
    st = client.app.state.st
    st.db.insert_task(
        {
            "text": "Fix memory leak in background worker",
            "done": True,
            "priority": "P2",
            "created_at": "2026-10-06T09:00:00+00:00",
            "completed_at": "2026-10-06T14:00:00+00:00",
        }
    )

    r = client.get("/api/activity/what-shipped?week=2026-10-05")
    assert r.status_code == 200
    data = r.json()
    assert data["week_start"] == "2026-10-05"
    assert data["counts"]["tasks"] >= 1

    # Save as note
    r_save = client.post(
        "/api/activity/what-shipped/save-as-note",
        json={"week": "2026-10-05", "markdown": data["markdown"]},
    )
    assert r_save.status_code == 200
    assert r_save.json()["ok"] is True
    note = r_save.json()["note"]
    assert "What Shipped" in note["title"]
    assert "shipped" in note["tags"]
