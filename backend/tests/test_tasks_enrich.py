"""Unit tests for task extraction, heuristic rules, local git repo discovery, and processor integration."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.process import Processor
from fleeting.services.llm import ENRICH_SCHEMA, _sanitize, heuristic_enrich
from fleeting.services.repos import discover_git_repos


# ============================================================================
# 1. Local Git Repo Discovery
# ============================================================================


def test_discover_git_repos_empty_and_missing(tmp_path):
    assert discover_git_repos("") == []
    assert discover_git_repos("   ") == []
    assert discover_git_repos(str(tmp_path / "non_existent_directory")) == []


def test_discover_git_repos_finds_child_repos(tmp_path):
    # Setup test workspace
    projects_dir = tmp_path / "Projects"
    projects_dir.mkdir()

    repo_a = projects_dir / "fleeting"
    repo_a.mkdir()
    (repo_a / ".git").mkdir()

    repo_b = projects_dir / "dotfiles"
    repo_b.mkdir()
    (repo_b / ".git").mkdir()

    not_a_repo = projects_dir / "notes"
    not_a_repo.mkdir()

    found = discover_git_repos(str(projects_dir))
    assert len(found) == 2
    names = [r["name"] for r in found]
    assert names == ["dotfiles", "fleeting"]  # sorted by name
    paths = [r["path"] for r in found]
    assert str(repo_a.resolve()) in paths
    assert str(repo_b.resolve()) in paths


def test_discover_git_repos_detects_repo_itself(tmp_path):
    repo_dir = tmp_path / "StandaloneRepo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    found = discover_git_repos(str(repo_dir))
    assert len(found) == 1
    assert found[0]["name"] == "standalonerepo"  # lowercase
    assert found[0]["path"] == str(repo_dir.resolve())


def test_discover_git_repos_detects_git_worktree_file(tmp_path):
    repo_dir = tmp_path / "worktree_repo"
    repo_dir.mkdir()
    git_file = repo_dir / ".git"
    git_file.write_text("gitdir: /some/path/.git/worktrees/worktree_repo")

    found = discover_git_repos(str(repo_dir))
    assert len(found) == 1
    assert found[0]["name"] == "worktree_repo"
    assert found[0]["path"] == str(repo_dir.resolve())


def test_discover_git_repos_multiple_comma_separated_and_deduplication(tmp_path):
    dir1 = tmp_path / "dir1"
    dir1.mkdir()
    repo1 = dir1 / "alpha"
    repo1.mkdir()
    (repo1 / ".git").mkdir()

    dir2 = tmp_path / "dir2"
    dir2.mkdir()
    repo2 = dir2 / "beta"
    repo2.mkdir()
    (repo2 / ".git").mkdir()

    watch_dirs = f"{dir1},  {dir2} , {dir1}"
    found = discover_git_repos(watch_dirs)
    assert len(found) == 2
    assert [r["name"] for r in found] == ["alpha", "beta"]


# ============================================================================
# 2. Heuristic Task Extraction
# ============================================================================


def test_heuristic_priority_extraction():
    today_iso = datetime.date.today().isoformat()

    # P1 matches: urgent, critical, asap, blocker, immediately, p1
    res1 = heuristic_enrich("todo: fix crashing auth blocker immediately")
    assert len(res1["action_items"]) == 1
    item1 = res1["action_items"][0]
    assert item1["priority"] == "P1"

    res2 = heuristic_enrich("task: deploy hotfix asap")
    assert res2["action_items"][0]["priority"] == "P1"

    # P3 matches: someday, eventually, low-priority, p3
    res3 = heuristic_enrich("todo: reorganize old downloads someday")
    assert res3["action_items"][0]["priority"] == "P3"

    res4 = heuristic_enrich("fix: clean up unused css low-priority")
    assert res4["action_items"][0]["priority"] == "P3"

    # Default P2
    res5 = heuristic_enrich("todo: write documentation for api")
    assert res5["action_items"][0]["priority"] == "P2"


def test_heuristic_due_date_extraction():
    today = datetime.date.today()
    tomorrow_iso = (today + datetime.timedelta(days=1)).isoformat()

    res1 = heuristic_enrich("todo: finish presentation by tomorrow")
    assert res1["action_items"][0]["due_date"] == tomorrow_iso

    res2 = heuristic_enrich("remember to submit taxes due 2026-10-15")
    assert res2["action_items"][0]["due_date"] == "2026-10-15"

    res3 = heuristic_enrich("todo: pay water bill before today")
    assert res3["action_items"][0]["due_date"] == today.isoformat()


def test_heuristic_repo_extraction():
    res1 = heuristic_enrich("todo: refactor auth module in fleeting repo")
    assert res1["action_items"][0]["repo"] == "fleeting"

    res2 = heuristic_enrich("fix: memory leak for backend repo")
    assert res2["action_items"][0]["repo"] == "backend"

    res3 = heuristic_enrich("task: add dark mode repo: frontend")
    assert res3["action_items"][0]["repo"] == "frontend"

    res4 = heuristic_enrich("deploy: migration script #infra")
    assert res4["action_items"][0]["repo"] == "infra"

    # Ordinary English phrases should not trigger false positive repo extraction
    res5 = heuristic_enrich("todo: buy milk for dinner")
    assert res5["action_items"][0]["repo"] is None

    res6 = heuristic_enrich("todo: pay in cash")
    assert res6["action_items"][0]["repo"] is None


def test_heuristic_enrich_combined():
    today = datetime.date.today()
    tomorrow_iso = (today + datetime.timedelta(days=1)).isoformat()
    note_text = (
        "Project status meeting notes\n"
        "Discussed upcoming release blockers.\n"
        "todo: patch security vulnerability urgent by tomorrow in fleeting repo\n"
        "task: update styling low-priority for frontend repo"
    )
    res = heuristic_enrich(note_text)
    items = res["action_items"]
    assert len(items) == 2

    assert items[0]["priority"] == "P1"
    assert items[0]["due_date"] == tomorrow_iso
    assert items[0]["repo"] == "fleeting"
    assert "patch security vulnerability" in items[0]["text"]

    assert items[1]["priority"] == "P3"
    assert items[1]["repo"] == "frontend"
    assert "update styling" in items[1]["text"]


# ============================================================================
# 3. LLM Schema & Sanitization
# ============================================================================


def test_enrich_schema_structure():
    assert "action_items" in ENRICH_SCHEMA["properties"]
    items_prop = ENRICH_SCHEMA["properties"]["action_items"]["items"]
    assert items_prop["type"] == "object"
    props = items_prop["properties"]
    assert "text" in props
    assert "priority" in props
    assert "due_date" in props
    assert "repo" in props
    assert items_prop["required"] == ["text"]


def test_sanitize_structured_dict_items():
    raw = {
        "title": "My Note",
        "summary": "Summary text",
        "tags": ["work"],
        "action_items": [
            {
                "text": "Critical bug fix",
                "priority": "p1",
                "due_date": "2026-10-05",
                "repo": "FLEETING",
            },
            {
                "text": "Minor cleanup",
                "priority": "invalid_priority",
                "due_date": "invalid_date",
                "repo": " #core_service ",
            },
            {
                "text": "   ",  # empty text should be discarded
                "priority": "P2",
            },
        ],
    }
    sanitized = _sanitize(raw)
    items = sanitized["action_items"]
    assert len(items) == 2

    assert items[0]["text"] == "Critical bug fix"
    assert items[0]["priority"] == "P1"
    assert items[0]["due_date"] == "2026-10-05"
    assert items[0]["repo"] == "fleeting"

    assert items[1]["text"] == "Minor cleanup"
    assert items[1]["priority"] == "P2"  # fallback
    assert items[1]["due_date"] is None  # invalid fallback
    assert items[1]["repo"] == "core_service"


def test_sanitize_legacy_string_items():
    raw = {
        "title": "Legacy Note",
        "summary": "Old summary",
        "tags": ["legacy"],
        "action_items": ["Simple string task", "Another task"],
    }
    sanitized = _sanitize(raw)
    items = sanitized["action_items"]
    assert len(items) == 2
    assert items[0]["text"] == "Simple string task"
    assert items[0]["priority"] == "P2"
    assert items[0]["due_date"] is None
    assert items[0]["repo"] is None


# ============================================================================
# 4. Processor Integration
# ============================================================================


@pytest.mark.anyio
async def test_processor_creates_tasks_in_db(tmp_path):
    db_path = tmp_path / "processor_test.db"
    db = Database(db_path)
    db.migrate()

    cfg = Config()
    cfg.paths.data_dir = tmp_path
    cfg.llm.provider = "none"  # triggers heuristic fallback
    cfg.notifications.desktop = False

    bus = EventBus()
    transcriber = MagicMock()

    processor = Processor(db=db, cfg=cfg, bus=bus, transcriber=transcriber)

    note = db.insert_note({
        "title": "Meeting Capture",
        "raw_text": "todo: patch memory leak urgent by tomorrow in fleeting repo",
        "type": "text",
        "status": "pending",
    })

    await processor._process(note["id"])

    updated_note = db.get_note(note["id"])
    assert updated_note["status"] == "done"

    tasks = db.list_tasks(status="all")
    assert len(tasks) == 1
    task = tasks[0]
    assert task["note_id"] == note["id"]
    assert task["priority"] == "P1"
    assert task["repo"] == "fleeting"
    today = datetime.date.today()
    assert task["due_date"] == (today + datetime.timedelta(days=1)).isoformat()
    assert "patch memory leak" in task["text"]

    # Verify notes.action_items JSON is synchronized
    note_items = updated_note["action_items"]
    assert len(note_items) == 1
    assert note_items[0]["id"] == task["id"]
    assert note_items[0]["priority"] == "P1"
    assert note_items[0]["repo"] == "fleeting"


@pytest.mark.anyio
async def test_processor_inherits_repo_from_source(tmp_path):
    db_path = tmp_path / "processor_source_repo.db"
    db = Database(db_path)
    db.migrate()

    cfg = Config()
    cfg.paths.data_dir = tmp_path
    cfg.llm.provider = "none"
    cfg.notifications.desktop = False

    bus = EventBus()
    transcriber = MagicMock()

    processor = Processor(db=db, cfg=cfg, bus=bus, transcriber=transcriber)

    # Note does not specify repo in the action item text, but has repo in source
    note = db.insert_note({
        "title": "Capture with source repo",
        "raw_text": "todo: write comprehensive documentation",
        "source": {"repo": "my-project"},
        "type": "text",
        "status": "pending",
    })

    await processor._process(note["id"])

    tasks = db.list_tasks(status="all")
    assert len(tasks) == 1
    assert tasks[0]["repo"] == "my-project"


@pytest.mark.anyio
async def test_processor_reprocessing_clears_old_tasks(tmp_path):
    db_path = tmp_path / "processor_reprocess.db"
    db = Database(db_path)
    db.migrate()

    cfg = Config()
    cfg.paths.data_dir = tmp_path
    cfg.llm.provider = "none"
    cfg.notifications.desktop = False

    bus = EventBus()
    transcriber = MagicMock()

    processor = Processor(db=db, cfg=cfg, bus=bus, transcriber=transcriber)

    note = db.insert_note({
        "title": "Capture to reprocess",
        "raw_text": "todo: initial task item",
        "type": "text",
        "status": "pending",
    })

    # First processing run
    await processor._process(note["id"])
    tasks_run1 = db.list_tasks(status="all")
    assert len(tasks_run1) == 1
    assert "initial task item" in tasks_run1[0]["text"]

    # Update raw_text and reprocess the same note
    db.update_note(note["id"], {
        "raw_text": "todo: replaced new task item",
        "status": "pending",
    })
    await processor._process(note["id"])

    # Verify existing tasks for note_id were cleared and not duplicated
    tasks_run2 = db.list_tasks(status="all")
    assert len(tasks_run2) == 1
    assert "replaced new task item" in tasks_run2[0]["text"]
    assert tasks_run2[0]["note_id"] == note["id"]

    updated_note = db.get_note(note["id"])
    assert len(updated_note["action_items"]) == 1
    assert "replaced new task item" in updated_note["action_items"][0]["text"]

