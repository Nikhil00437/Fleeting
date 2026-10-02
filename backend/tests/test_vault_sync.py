"""Integration tests for vault synchronization, ingestion, and resync API."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fleeting.config import Config, PathsConfig
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.markdown import parse_note_md, render_note_md, sync_note, vault_path_for
from fleeting.services.vault_watcher import (
    VaultSyncRegistry,
    VaultWatcher,
    resync_all,
    sync_file_change,
    sync_registry,
)


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.migrate()

    bus = EventBus()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    cfg.paths.vault_sync = True
    vault_dir = Path(cfg.paths.vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    sync_registry.clear()
    return db, bus, cfg, vault_dir


def test_sync_file_change_echo_suppression(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "Echo Note",
        "type": "text",
        "summary": "Initial summary",
        "action_items": [],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None
    assert path.exists()

    # Calling sync_file_change right after Fleeting write should be suppressed as echo
    result = sync_file_change(path, db, bus, cfg)
    assert result is None


def test_sync_file_change_toggle_task(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "Task Toggle Note",
        "type": "text",
        "summary": "Note with tasks",
        "action_items": [
            {"id": "t1", "text": "First task", "done": False, "priority": "P2"},
            {"id": "t2", "text": "Second task", "done": False, "priority": "P1"},
        ],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None

    tasks_before = db.list_tasks(status="all", limit=10)
    assert len(tasks_before) == 2
    t1_before = [t for t in tasks_before if "First task" in t["text"]][0]
    assert t1_before["done"] is False
    assert t1_before["completed_at"] is None

    # User modifies file on disk: marks First task as done
    content = path.read_text(encoding="utf-8")
    modified_content = content.replace("- [ ] First task", "- [x] First task")
    path.write_text(modified_content, encoding="utf-8")

    # Mock bus listener
    events = []
    q = bus.subscribe()

    result = sync_file_change(path, db, bus, cfg)
    assert result is not None
    assert result["action"] == "updated"
    assert result["note_id"] == note["id"]

    # Verify task in DB updated
    t1_after = db.get_task(t1_before["id"])
    assert t1_after is not None
    assert t1_after["done"] is True
    assert t1_after["completed_at"] is not None

    # Verify note action_items synced in DB
    refreshed_note = db.get_note(note["id"])
    assert refreshed_note["action_items"][0]["done"] is True

    # Check SSE events published
    while not q.empty():
        events.append(q.get_nowait())
    bus.unsubscribe(q)

    event_types = [e for e in events if "task.updated" in e or "note.updated" in e]
    assert len(event_types) >= 1


def test_sync_file_change_add_task(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "Add Task Note",
        "type": "text",
        "summary": "Existing note",
        "action_items": [
            {"text": "Existing task", "done": False},
        ],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None

    # User appends new task in markdown
    content = path.read_text(encoding="utf-8")
    modified_content = content.rstrip() + "\n- [ ] New priority task [P1] [due:2026-10-15] [repo:fleeting]\n"
    path.write_text(modified_content, encoding="utf-8")

    result = sync_file_change(path, db, bus, cfg)
    assert result is not None
    assert result["action"] == "updated"

    tasks = db.list_tasks(status="all", limit=10)
    assert len(tasks) == 2
    new_t = [t for t in tasks if t["text"] == "New priority task"][0]
    assert new_t["priority"] == "P1"
    assert new_t["due_date"] == "2026-10-15"
    assert new_t["repo"] == "fleeting"
    assert new_t["done"] is False


def test_sync_file_change_delete_task(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "Delete Task Note",
        "type": "text",
        "summary": "Existing note",
        "action_items": [
            {"text": "Keep me", "done": False},
            {"text": "Delete me", "done": False},
        ],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None

    # User removes "Delete me" from checklist
    content = path.read_text(encoding="utf-8")
    lines = [l for l in content.splitlines() if "Delete me" not in l]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = sync_file_change(path, db, bus, cfg)
    assert result is not None
    assert result["action"] == "updated"

    tasks = db.list_tasks(status="all", limit=10)
    assert len(tasks) == 1
    assert tasks[0]["text"] == "Keep me"


def test_sync_file_change_modify_title_and_tags(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "Original Title",
        "type": "text",
        "summary": "Original summary",
        "tags": ["alpha"],
        "action_items": [],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None

    content = path.read_text(encoding="utf-8")
    # Change title and add tag
    modified = content.replace("# Original Title", "# Updated Title by User")
    modified = modified.replace("  - alpha", "  - alpha\n  - beta")
    path.write_text(modified, encoding="utf-8")

    result = sync_file_change(path, db, bus, cfg)
    assert result is not None
    assert result["action"] == "updated"
    assert result["note_id"] == note["id"]

    updated_note = db.get_note(note["id"])
    assert updated_note["title"] == "Updated Title by User"
    assert set(updated_note["tags"]) == {"alpha", "beta"}


def test_sync_file_change_untracked_new_file(test_env):
    db, bus, cfg, vault_dir = test_env
    new_file = vault_dir / "2026-10-02 external-idea.md"
    raw_content = """# External Idea

This note was created directly in Obsidian.

## Action items
- [ ] Review external proposal [P1]

## Content
Some detailed body thoughts.
"""
    new_file.write_text(raw_content, encoding="utf-8")

    result = sync_file_change(new_file, db, bus, cfg)
    assert result is not None
    assert result["action"] == "created"
    note_id = result["note_id"]

    # Verify note in DB
    note = db.get_note(note_id)
    assert note is not None
    assert note["title"] == "External Idea"
    assert note["summary"] == "This note was created directly in Obsidian."
    assert "Some detailed body thoughts." in note["raw_text"]

    # Verify task in DB
    tasks = db.list_tasks(status="all", limit=10)
    assert len(tasks) == 1
    assert tasks[0]["text"] == "Review external proposal"
    assert tasks[0]["priority"] == "P1"

    # Verify file updated on disk with frontmatter id
    updated_file_content = new_file.read_text(encoding="utf-8")
    assert f"id: {note_id}" in updated_file_content

    # Subsequent check should be treated as echo
    assert sync_registry.is_echo(new_file, updated_file_content) is True


def test_sync_file_change_deletion_archives_note(test_env):
    db, bus, cfg, vault_dir = test_env
    note = db.insert_note({
        "title": "To Be Deleted",
        "type": "text",
        "summary": "Will be archived on deletion",
        "action_items": [],
    })
    path = sync_note(cfg.paths, note)
    assert path is not None
    assert path.exists()

    # User deletes the file from vault
    path.unlink()

    result = sync_file_change(path, db, bus, cfg)
    assert result is not None
    assert result["action"] == "archived"
    assert result["note_id"] == note["id"]

    # Verify note is archived in DB
    refreshed = db.get_note(note["id"])
    assert refreshed["archived"] == 1


def test_resync_all(test_env):
    db, bus, cfg, vault_dir = test_env

    # 1. Existing note on disk with user modification
    n1 = db.insert_note({
        "title": "Note 1",
        "type": "text",
        "action_items": [{"text": "Task 1", "done": False}],
    })
    p1 = sync_note(cfg.paths, n1)
    p1_content = p1.read_text(encoding="utf-8").replace("- [ ] Task 1", "- [x] Task 1")
    p1.write_text(p1_content, encoding="utf-8")

    # 2. Untracked file in vault
    p2 = vault_dir / "untracked.md"
    p2.write_text("# Untracked Note\n\nSome summary\n\n- [ ] Untracked task\n", encoding="utf-8")

    # 3. Note in DB missing from disk
    n3 = db.insert_note({
        "title": "Note 3 In DB Only",
        "type": "text",
        "summary": "Not on disk yet",
        "action_items": [],
    })

    res = resync_all(vault_dir, db, bus, cfg)
    assert res["ok"] is True
    assert res["imported_notes"] >= 1
    assert res["synced_notes"] >= 1

    # Verify n1 task was toggled to done
    tasks_n1 = [t for t in db.list_tasks(status="all", limit=50) if t["note_id"] == n1["id"]]
    assert tasks_n1[0]["done"] is True

    # Verify p2 was imported and frontmatter added
    assert "id:" in p2.read_text(encoding="utf-8")

    # Verify n3 was exported to disk
    expected_p3 = vault_path_for(cfg.paths, n3)
    assert expected_p3.exists()


def test_settings_resync_api(client):
    res = client.post("/api/settings/vault/resync")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "synced_notes" in data
    assert "imported_notes" in data
    assert "tasks_updated" in data


def test_parse_note_md_preserves_arbitrary_h2_sections():
    content = """# Document

Summary text.

## Action items
- [ ] Do work

## Notes and Thoughts
Some notes that should not be dropped.

## Reference Architecture
Architecture details here.
"""
    parsed = parse_note_md(content)
    assert len(parsed["action_items"]) == 1
    assert parsed["summary"] == "Summary text."
    assert "## Notes and Thoughts" in parsed["raw_text"]
    assert "Some notes that should not be dropped." in parsed["raw_text"]
    assert "## Reference Architecture" in parsed["raw_text"]
    assert "Architecture details here." in parsed["raw_text"]
