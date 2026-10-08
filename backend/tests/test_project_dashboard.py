"""#167 per-project dashboards: time, apps, branches, commits, tasks and notes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.projects import get_project_dashboard, list_projects_summary


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_dash.db")
    database.migrate()
    return database


def test_list_projects_summary_empty(db: Database) -> None:
    assert list_projects_summary(db) == []


def test_list_projects_summary_aggregates_projects(db: Database) -> None:
    # 2 sessions for "fleeting" across 2 days, 1 session for "dotfiles"
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('ghostty', 'nvim', '2026-10-07T10:00:00', '2026-10-07T10:30:00', 1800, '2026-10-07', 'fleeting', 'main')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('ghostty', 'test', '2026-10-08T11:00:00', '2026-10-08T12:00:00', 3600, '2026-10-08', 'Fleeting', 'feature/x')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('code', 'edit', '2026-10-08T09:00:00', '2026-10-08T09:20:00', 1200, '2026-10-08', 'dotfiles', 'master')"
    )
    # unlabelled session (should not appear as a project)
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project)"
        " VALUES ('firefox', 'youtube', '2026-10-08T12:00:00', '2026-10-08T12:10:00', 600, '2026-10-08', NULL)"
    )

    summaries = list_projects_summary(db)
    assert len(summaries) == 2
    # ordered by total seconds desc
    assert summaries[0]["project"] == "fleeting"
    assert summaries[0]["total_seconds"] == 5400
    assert summaries[0]["active_days"] == 2
    assert summaries[0]["last_active"] == "2026-10-08"

    assert summaries[1]["project"] == "dotfiles"
    assert summaries[1]["total_seconds"] == 1200
    assert summaries[1]["active_days"] == 1
    assert summaries[1]["last_active"] == "2026-10-08"


def test_get_project_dashboard_combines_telemetry_commits_tasks_notes(db: Database) -> None:
    # 1. Activity telemetry
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('ghostty', 'editor', '2026-10-08T10:00:00', '2026-10-08T11:00:00', 3600, '2026-10-08', 'fleeting', 'main')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('firefox', 'docs', '2026-10-08T11:00:00', '2026-10-08T11:30:00', 1800, '2026-10-08', 'fleeting', 'main')"
    )
    db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, project, branch)"
        " VALUES ('ghostty', 'cli', '2026-10-07T14:00:00', '2026-10-07T14:15:00', 900, '2026-10-07', 'fleeting', 'feature/dash')"
    )

    # 2. Commits
    db.execute(
        "INSERT INTO commits (repo, subject, author, committed_at, recorded_at)"
        " VALUES ('fleeting', 'feat: initial dashboard', 'Alice', '2026-10-08T10:30:00Z', '2026-10-08T10:30:00Z')"
    )
    db.execute(
        "INSERT INTO commits (repo, subject, author, committed_at, recorded_at)"
        " VALUES ('other_repo', 'fix: unrelated', 'Bob', '2026-10-08T10:00:00Z', '2026-10-08T10:00:00Z')"
    )

    # 3. Tasks (one linked via repo, one via hashtag, one completed)
    note = db.insert_note({"type": "text", "title": "Dev Plan", "raw_text": "Working on #fleeting"})
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, repo, created_at, estimate_min, spent_min)"
        " VALUES ('t1', ?, 'Build project dashboard', 0, 'P1', 'fleeting', '2026-10-08T09:00:00Z', 60, 45)",
        (note["id"],),
    )
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, repo, created_at, completed_at)"
        " VALUES ('t2', ?, 'Fix #fleeting auth bug', 1, 'P2', NULL, '2026-10-07T09:00:00Z', '2026-10-08T11:00:00Z')",
        (note["id"],),
    )
    db.execute(
        "INSERT INTO tasks (id, note_id, text, done, priority, repo, created_at)"
        " VALUES ('t3', ?, 'Unrelated task', 0, 'P3', 'other', '2026-10-08T09:00:00Z')",
        (note["id"],),
    )

    # 4. Notes
    db.insert_note({"type": "text", "title": "Architecture specs", "raw_text": "Specs for #fleeting app", "tags": ["fleeting"]})
    db.insert_note({"type": "text", "title": "Random note", "raw_text": "Grocery list", "tags": ["home"]})

    dash = get_project_dashboard(db, "fleeting", days=30)
    assert dash["project"] == "fleeting"
    assert dash["total_seconds"] == 6300
    assert dash["active_days"] == 2
    assert dash["last_active"] == "2026-10-08"

    # Daily breakdown
    assert len(dash["daily_breakdown"]) == 2
    assert dash["daily_breakdown"][0]["day"] == "2026-10-07"
    assert dash["daily_breakdown"][0]["seconds"] == 900
    assert dash["daily_breakdown"][1]["day"] == "2026-10-08"
    assert dash["daily_breakdown"][1]["seconds"] == 5400

    # Apps
    apps = {a["app"]: a["seconds"] for a in dash["apps"]}
    assert apps["ghostty"] == 4500
    assert apps["firefox"] == 1800

    # Branches
    branches = {b["branch"]: b["seconds"] for b in dash["branches"]}
    assert branches["main"] == 5400
    assert branches["feature/dash"] == 900

    # Commits
    assert len(dash["commits"]) == 1
    assert dash["commits"][0]["repo"] == "fleeting"
    assert dash["commits"][0]["subject"] == "feat: initial dashboard"

    # Tasks
    assert dash["tasks"]["total"] == 2
    assert dash["tasks"]["completed"] == 1
    assert dash["tasks"]["pending"] == 1
    assert len(dash["tasks"]["items"]) == 2

    # Notes
    assert len(dash["notes"]) == 2  # note 1 has hashtag in text, note 2 has tag
    titles = [n["title"] for n in dash["notes"]]
    assert "Architecture specs" in titles
    assert "Dev Plan" in titles


def test_project_dashboard_api(client) -> None:
    # Test via API
    resp = client.get("/api/activity/projects/summary")
    assert resp.status_code == 200
    assert "projects" in resp.json()

    resp = client.get("/api/activity/projects/fleeting/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["project"] == "fleeting"
    assert "total_seconds" in data
    assert "apps" in data
    assert "tasks" in data
