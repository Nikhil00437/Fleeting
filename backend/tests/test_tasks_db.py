"""Tests for relational tasks table, migration, CRUD, and note synchronization."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from fleeting.db import Database, new_id, now_iso
from fleeting.models import ActionItem, TaskCreateIn, TaskOut, TaskUpdateIn


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def test_tasks_table_created_on_migrate(tmp_path):
    """Verify tasks table and its indexes are created on migration."""
    database = Database(tmp_path / "schema_test.db")
    database.migrate()

    conn = database.conn
    # Check table existence
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "tasks" in tables

    # Check columns
    columns = {
        row["name"]: row["type"].upper()
        for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }
    assert "id" in columns
    assert "note_id" in columns
    assert "text" in columns
    assert "done" in columns
    assert "priority" in columns
    assert "due_date" in columns
    assert "repo" in columns
    assert "created_at" in columns
    assert "completed_at" in columns

    # Check indexes
    indexes = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tasks'"
        ).fetchall()
    ]
    assert "idx_tasks_note_id" in indexes
    assert "idx_tasks_done" in indexes
    assert "idx_tasks_priority" in indexes
    assert "idx_tasks_due_date" in indexes
    assert "idx_tasks_repo" in indexes


def test_migration_from_notes_action_items(tmp_path):
    """Verify idempotent migration of existing action items from notes into tasks table."""
    db_path = tmp_path / "migrate_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'text',
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            action_items TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '{}',
            audio_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            pinned INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            processed_at TEXT
        );
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (4);
        """
    )
    # Insert notes before migration:
    # Note 1: 2 action items (one open, one done)
    conn.execute(
        """
        INSERT INTO notes (id, title, action_items, created_at, updated_at, archived)
        VALUES ('n1', 'First Note', :items, '2026-10-01T10:00:00Z', '2026-10-01T11:00:00Z', 0)
        """,
        {
            "items": json.dumps([
                {
                    "id": "t1",
                    "text": "Task One",
                    "done": False,
                    "priority": "P1",
                    "due_date": "2026-10-02",
                    "repo": "fleeting",
                },
                {
                    "id": "t2",
                    "text": "Task Two",
                    "done": True,
                    "priority": "P2",
                },
            ])
        },
    )
    # Note 2: archived note (should not be migrated into active tasks)
    conn.execute(
        """
        INSERT INTO notes (id, title, action_items, created_at, updated_at, archived)
        VALUES ('n2', 'Archived Note', :items, '2026-09-01T10:00:00Z', '2026-09-01T10:00:00Z', 1)
        """,
        {
            "items": json.dumps([
                {"id": "t1", "text": "Archived Task", "done": False}
            ])
        },
    )
    # Note 3: Note with simple legacy items without priority/due_date
    conn.execute(
        """
        INSERT INTO notes (id, title, action_items, created_at, updated_at, archived)
        VALUES ('n3', 'Legacy Note', :items, '2026-10-01T12:00:00Z', '2026-10-01T12:00:00Z', 0)
        """,
        {
            "items": json.dumps([
                {"id": "t1", "text": "Legacy Task", "done": False}
            ])
        },
    )
    conn.commit()
    conn.close()

    # Now open with Database and migrate
    database = Database(db_path)
    database.migrate()

    tasks = database.list_tasks(status="all")
    assert len(tasks) == 3

    t1 = next(t for t in tasks if "Task One" in t["text"])
    assert t1["priority"] == "P1"
    assert t1["due_date"] == "2026-10-02"
    assert t1["repo"] == "fleeting"
    assert t1["done"] is False
    assert t1["completed_at"] is None

    t2 = next(t for t in tasks if "Task Two" in t["text"])
    assert t2["done"] is True
    assert t2["completed_at"] == "2026-10-01T11:00:00Z"
    assert t2["priority"] == "P2"

    t3 = next(t for t in tasks if "Legacy Task" in t["text"])
    assert t3["priority"] == "P2"
    assert t3["due_date"] is None
    assert t3["repo"] is None

    # Verify idempotency: run migration again
    database._migrate_action_items()
    assert len(database.list_tasks(status="all")) == 3


def test_task_crud(db):
    """Test insert, get, update, toggle, and delete operations on tasks."""
    note = db.insert_note({"title": "CRUD Test Note"})

    # 1. Insert task
    task_in = {
        "note_id": note["id"],
        "text": "Write database tests",
        "priority": "P1",
        "due_date": "2026-10-05",
        "repo": "fleeting",
    }
    task = db.insert_task(task_in)
    assert task["id"]
    assert task["note_id"] == note["id"]
    assert task["note_title"] == "CRUD Test Note"
    assert task["text"] == "Write database tests"
    assert task["done"] is False
    assert task["priority"] == "P1"
    assert task["due_date"] == "2026-10-05"
    assert task["repo"] == "fleeting"
    assert task["completed_at"] is None
    assert task["created_at"]

    # 2. Get task
    fetched = db.get_task(task["id"])
    assert fetched is not None
    assert fetched["id"] == task["id"]
    assert fetched["text"] == task["text"]

    # 3. Update task
    updated = db.update_task(
        task["id"],
        {
            "text": "Write comprehensive database tests",
            "priority": "P3",
            "due_date": "2026-10-10",
            "repo": "core",
        },
    )
    assert updated is not None
    assert updated["text"] == "Write comprehensive database tests"
    assert updated["priority"] == "P3"
    assert updated["due_date"] == "2026-10-10"
    assert updated["repo"] == "core"

    # 4. Toggle task
    toggled = db.toggle_task(task["id"])
    assert toggled is not None
    assert toggled["done"] is True
    assert toggled["completed_at"] is not None

    # Toggle back
    untoggled = db.toggle_task(task["id"])
    assert untoggled is not None
    assert untoggled["done"] is False
    assert untoggled["completed_at"] is None

    # 5. Delete task
    deleted = db.delete_task(task["id"])
    assert deleted is not None
    assert deleted["id"] == task["id"]
    assert db.get_task(task["id"]) is None


def test_list_tasks_filtering(db):
    """Test filtering tasks by status, priority, repo, due date, and search query."""
    note1 = db.insert_note({"title": "Frontend App"})
    note2 = db.insert_note({"title": "Backend API"})

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (datetime.now().astimezone() + timedelta(days=5)).strftime("%Y-%m-%d")

    # Insert test tasks
    t1 = db.insert_task({
        "note_id": note1["id"],
        "text": "Fix CSS styles for buttons",
        "priority": "P1",
        "repo": "frontend",
        "due_date": today,
    })
    t2 = db.insert_task({
        "note_id": note1["id"],
        "text": "Add dark mode toggle",
        "priority": "P2",
        "repo": "frontend",
        "due_date": yesterday,  # overdue
    })
    t3 = db.insert_task({
        "note_id": note2["id"],
        "text": "Implement rate limiting",
        "priority": "P3",
        "repo": "backend",
        "due_date": next_week,
    })
    t4 = db.insert_task({
        "note_id": note2["id"],
        "text": "Setup CI pipeline",
        "priority": "P1",
        "repo": "infra",
        "due_date": None,
    })
    # Mark t4 as done
    db.toggle_task(t4["id"])

    # 1. Filter by status
    open_tasks = db.list_tasks(status="open")
    assert len(open_tasks) == 3
    assert {t["id"] for t in open_tasks} == {t1["id"], t2["id"], t3["id"]}

    done_tasks = db.list_tasks(status="done")
    assert len(done_tasks) == 1
    assert done_tasks[0]["id"] == t4["id"]

    all_tasks = db.list_tasks(status="all")
    assert len(all_tasks) == 4

    # 2. Filter by priority
    p1_tasks = db.list_tasks(status="all", priority="P1")
    assert len(p1_tasks) == 2
    assert {t["id"] for t in p1_tasks} == {t1["id"], t4["id"]}

    p2_open = db.list_tasks(status="open", priority="P2")
    assert len(p2_open) == 1
    assert p2_open[0]["id"] == t2["id"]

    # 3. Filter by repo
    fe_tasks = db.list_tasks(status="open", repo="frontend")
    assert len(fe_tasks) == 2
    assert {t["id"] for t in fe_tasks} == {t1["id"], t2["id"]}

    # 4. Filter by due
    overdue_tasks = db.list_tasks(status="open", due="overdue")
    assert len(overdue_tasks) == 1
    assert overdue_tasks[0]["id"] == t2["id"]

    today_tasks = db.list_tasks(status="open", due="today")
    assert len(today_tasks) == 1
    assert today_tasks[0]["id"] == t1["id"]

    week_tasks = db.list_tasks(status="open", due="week")
    assert len(week_tasks) == 2
    assert {t["id"] for t in week_tasks} == {t1["id"], t3["id"]}

    nodate_tasks = db.list_tasks(status="all", due="nodate")
    assert len(nodate_tasks) == 1
    assert nodate_tasks[0]["id"] == t4["id"]

    # 5. Search query q
    search_res = db.list_tasks(status="all", q="CSS")
    assert len(search_res) == 1
    assert search_res[0]["id"] == t1["id"]

    search_by_note = db.list_tasks(status="all", q="Backend API")
    assert len(search_by_note) == 2
    assert {t["id"] for t in search_by_note} == {t3["id"], t4["id"]}

    # 6. Pagination
    page1 = db.list_tasks(status="all", limit=2, offset=0)
    page2 = db.list_tasks(status="all", limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {t["id"] for t in page1}.isdisjoint({t["id"] for t in page2})


def test_bidirectional_sync_tasks_to_note(db):
    """Mutating tasks table must automatically sync notes.action_items JSON."""
    note = db.insert_note({"title": "Sync Note 1", "action_items": []})
    assert note["action_items"] == []

    # Insert task -> should appear in note.action_items
    task = db.insert_task({
        "note_id": note["id"],
        "text": "Item A",
        "priority": "P1",
        "due_date": "2026-10-15",
        "repo": "fleeting",
    })
    note_fresh = db.get_note(note["id"])
    assert len(note_fresh["action_items"]) == 1
    ai = note_fresh["action_items"][0]
    assert ai["id"] == task["id"]
    assert ai["text"] == "Item A"
    assert ai["priority"] == "P1"
    assert ai["due_date"] == "2026-10-15"
    assert ai["repo"] == "fleeting"
    assert ai["done"] is False

    # Update task -> note.action_items updated
    db.update_task(task["id"], {"text": "Item A Updated", "priority": "P3"})
    note_fresh = db.get_note(note["id"])
    assert note_fresh["action_items"][0]["text"] == "Item A Updated"
    assert note_fresh["action_items"][0]["priority"] == "P3"

    # Toggle task -> note.action_items done status updated
    db.toggle_task(task["id"])
    note_fresh = db.get_note(note["id"])
    assert note_fresh["action_items"][0]["done"] is True
    assert note_fresh["action_items"][0]["completed_at"] is not None

    # Delete task -> note.action_items becomes empty
    db.delete_task(task["id"])
    note_fresh = db.get_note(note["id"])
    assert note_fresh["action_items"] == []


def test_bidirectional_sync_note_to_tasks(db):
    """Mutating note action_items via insert_note or update_note must sync tasks table."""
    # Insert note with action items
    note = db.insert_note({
        "title": "Sync Note 2",
        "action_items": [
            {"id": "t1", "text": "From Note", "priority": "P2", "done": False}
        ],
    })
    tasks = db.list_tasks(status="all")
    assert len(tasks) == 1
    assert tasks[0]["text"] == "From Note"
    assert tasks[0]["note_id"] == note["id"]

    # Update note action items (toggle done and add new item)
    task_id = tasks[0]["id"]
    db.update_note(
        note["id"],
        {
            "action_items": [
                {"id": task_id, "text": "From Note Done", "priority": "P2", "done": True},
                {"id": "t2", "text": "Second Item", "priority": "P1", "done": False},
            ]
        },
    )
    tasks_after = db.list_tasks(status="all")
    assert len(tasks_after) == 2

    t1 = next(t for t in tasks_after if t["id"] == task_id)
    assert t1["done"] is True
    assert t1["text"] == "From Note Done"

    t2 = next(t for t in tasks_after if t["id"] != task_id)
    assert t2["text"] == "Second Item"
    assert t2["priority"] == "P1"
    assert t2["done"] is False

    # Clear action items on note -> tasks table removes them
    db.update_note(note["id"], {"action_items": []})
    assert len(db.list_tasks(status="all")) == 0


def test_task_stats(db):
    """Verify task_stats returns accurate counts and breakdown."""
    note = db.insert_note({"title": "Stats Note"})
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=2)).strftime("%Y-%m-%d")

    # 1 open P1 today
    db.insert_task({"note_id": note["id"], "text": "T1", "priority": "P1", "due_date": today})
    # 1 open P2 overdue
    db.insert_task({"note_id": note["id"], "text": "T2", "priority": "P2", "due_date": yesterday})
    # 1 open P3 no date
    db.insert_task({"note_id": note["id"], "text": "T3", "priority": "P3"})
    # 1 done P1
    t4 = db.insert_task({"note_id": note["id"], "text": "T4", "priority": "P1"})
    db.toggle_task(t4["id"])

    stats = db.task_stats()
    assert stats["total"] == 4
    assert stats["open"] == 3
    assert stats["done"] == 1
    assert stats["completion_rate"] == 0.25
    assert stats["by_priority"]["P1"] == 1  # open P1
    assert stats["by_priority"]["P2"] == 1  # open P2
    assert stats["by_priority"]["P3"] == 1  # open P3
    assert stats["overdue"] == 1
    assert stats["due_today"] == 1


def test_task_repos(db):
    """Verify task_repos returns distinct repositories with item counts."""
    note = db.insert_note({"title": "Repos Note"})
    db.insert_task({"note_id": note["id"], "text": "T1", "repo": "fleeting"})
    db.insert_task({"note_id": note["id"], "text": "T2", "repo": "fleeting"})
    db.insert_task({"note_id": note["id"], "text": "T3", "repo": "dotfiles"})
    db.insert_task({"note_id": note["id"], "text": "T4", "repo": None})

    repos = db.task_repos()
    repo_map = {r["repo"]: r["count"] for r in repos}
    assert repo_map["fleeting"] == 2
    assert repo_map["dotfiles"] == 1
    assert None not in repo_map
    assert "" not in repo_map


def test_standalone_task_creation(db):
    """Creating a task without note_id creates or attaches to an Inbox note."""
    task = db.insert_task({"text": "Quick standalone thought", "priority": "P1"})
    assert task["id"]
    assert task["note_id"]
    assert task["text"] == "Quick standalone thought"

    note = db.get_note(task["note_id"])
    assert note is not None
    assert "Inbox" in note["title"]
    assert any(item["id"] == task["id"] for item in note["action_items"])


def test_note_deletion_cascades_to_tasks(db):
    """Deleting a note deletes all associated tasks in tasks table."""
    note = db.insert_note({"title": "Doomed Note"})
    t1 = db.insert_task({"note_id": note["id"], "text": "Doomed Task 1"})
    t2 = db.insert_task({"note_id": note["id"], "text": "Doomed Task 2"})

    assert db.get_task(t1["id"]) is not None
    assert db.get_task(t2["id"]) is not None

    db.delete_note(note["id"])
    assert db.get_task(t1["id"]) is None
    assert db.get_task(t2["id"]) is None


def test_pydantic_task_models():
    """Verify Pydantic models validate priority, due_date, and repo formatting."""
    # ActionItem defaults
    item = ActionItem(id="t1", text="Clean up")
    assert item.priority == "P2"
    assert item.due_date is None
    assert item.repo is None
    assert item.done is False

    # TaskOut model
    task_out = TaskOut(
        id="t1",
        note_id="n1",
        note_title="My Note",
        text="Review PR",
        priority="P1",
        due_date="2026-10-02",
        repo="FLEETING",
        created_at="2026-10-01T10:00:00Z",
    )
    assert task_out.repo == "fleeting"
    assert task_out.priority == "P1"

    # TaskCreateIn normalization and validation
    create_in = TaskCreateIn(
        text="Submit report",
        priority="p1",  # should normalize to P1
        repo="  My-Repo  ",  # should strip and lowercase
        due_date="2026-12-31",
    )
    assert create_in.priority == "P1"
    assert create_in.repo == "my-repo"
    assert create_in.due_date == "2026-12-31"

    # TaskUpdateIn
    update_in = TaskUpdateIn(priority="P3", repo="Fleeting")
    assert update_in.priority == "P3"
    assert update_in.repo == "fleeting"

    # Invalid priority throws validation error
    with pytest.raises(Exception):
        TaskCreateIn(text="Bad priority", priority="P5")

    # Invalid due date throws validation error
    with pytest.raises(Exception):
        TaskCreateIn(text="Bad date", due_date="tomorrow")


def test_update_note_with_action_item_models_and_priority_none(db):
    """Verify update_note works with ActionItem Pydantic models and update_task handles priority=None."""
    note = db.insert_note({"title": "Model Serialization Note"})

    # 1. update_note with ActionItem model instances
    items = [
        ActionItem(id="t1", text="Task via model", priority="P1", repo="core"),
        ActionItem(id="t2", text="Second model task", priority="P3"),
    ]
    updated = db.update_note(note["id"], {"action_items": items})
    assert updated is not None
    assert len(updated["action_items"]) == 2
    assert updated["action_items"][0]["text"] == "Task via model"
    assert updated["action_items"][0]["priority"] == "P1"

    # Verify tasks table synced properly
    tasks = db.list_tasks(status="all")
    assert len(tasks) == 2

    # 2. update_task with explicit priority=None -> must fallback to P2
    task1_id = tasks[0]["id"]
    t1_updated = db.update_task(task1_id, {"priority": None})
    assert t1_updated is not None
    assert t1_updated["priority"] == "P2"


def test_migration_malformed_json_resilience(tmp_path):
    """Verify _migrate_action_items does not crash on corrupted JSON in action_items column."""
    db_path = tmp_path / "corrupt_test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'text',
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            raw_text TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            action_items TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '{}',
            audio_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            pinned INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            processed_at TEXT
        );
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version (version) VALUES (4);
        INSERT INTO notes (id, title, action_items, created_at, updated_at, archived)
        VALUES ('bad_n1', 'Corrupt Note', '{invalid json', '2026-10-01T10:00:00Z', '2026-10-01T10:00:00Z', 0);
        """
    )
    conn.commit()
    conn.close()

    database = Database(db_path)
    database.migrate()
    assert database.list_tasks(status="all") == []
