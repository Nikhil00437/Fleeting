import pytest
from unittest.mock import patch
from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.actions import execute_action, AVAILABLE_ACTIONS


@pytest.fixture
def env(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    bus = EventBus()
    return db, cfg, bus


def test_delete_all_tasks(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1", "priority": "P1"})
    t2 = db.insert_task({"text": "Task 2", "priority": "P2"})
    assert len(db.list_tasks(status="all")) == 2

    events = []
    bus.subscribe("task.deleted", lambda data: events.append(data))

    res = execute_action("delete_tasks", {"all": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["count"] == 2
    assert len(db.list_tasks(status="all")) == 0
    assert len(events) == 2


def test_create_and_toggle_task(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("task.created", lambda data: events.append(("created", data)))
    bus.subscribe("task.updated", lambda data: events.append(("updated", data)))

    res = execute_action("create_task", {"text": "Buy groceries", "priority": "P1"}, db, cfg, bus)
    assert res["ok"] is True
    task_id = res["task"]["id"]
    assert res["task"]["text"] == "Buy groceries"
    assert res["task"]["priority"] == "P1"

    toggle_res = execute_action("toggle_task", {"task_id": task_id}, db, cfg, bus)
    assert toggle_res["ok"] is True
    assert toggle_res["task"]["done"] == 1


def test_update_task(env):
    db, cfg, bus = env
    t = db.insert_task({"text": "Initial task", "priority": "P3"})
    events = []
    bus.subscribe("task.updated", lambda data: events.append(data))

    res = execute_action(
        "update_task",
        {"task_id": t["id"], "text": "Updated task", "priority": "P1", "repo": "fleeting"},
        db,
        cfg,
        bus,
    )
    assert res["ok"] is True
    assert res["task"]["text"] == "Updated task"
    assert res["task"]["priority"] == "P1"
    assert res["task"]["repo"] == "fleeting"
    assert len(events) == 1


def test_delete_tasks_by_ids(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1"})
    t2 = db.insert_task({"text": "Task 2"})
    t3 = db.insert_task({"text": "Task 3"})
    assert len(db.list_tasks(status="all")) == 3

    events = []
    bus.subscribe("task.deleted", lambda data: events.append(data))

    res = execute_action("delete_tasks", {"ids": [t1["id"], t3["id"]]}, db, cfg, bus)
    assert res["ok"] is True
    assert res["count"] == 2
    remaining = db.list_tasks(status="all")
    assert len(remaining) == 1
    assert remaining[0]["id"] == t2["id"]
    assert len(events) == 2


def test_create_note_and_sync(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("note.created", lambda data: events.append(data))

    res = execute_action(
        "create_note",
        {"title": "Meeting Notes", "content": "Discuss Q4 objectives", "tags": ["work", "q4"]},
        db,
        cfg,
        bus,
    )
    assert res["ok"] is True
    note = res["note"]
    assert note["title"] == "Meeting Notes"
    assert note["raw_text"] == "Discuss Q4 objectives"
    assert "work" in note["tags"]
    assert len(events) == 1


def test_delete_note_and_cascade(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Project plan", "raw_text": "Plan", "status": "done"})
    t1 = db.insert_task({"text": "Task under note", "note_id": note["id"]})

    events_note = []
    events_task = []
    bus.subscribe("note.deleted", lambda data: events_note.append(data))
    bus.subscribe("task.deleted", lambda data: events_task.append(data))

    res = execute_action("delete_note", {"note_id": note["id"]}, db, cfg, bus)
    assert res["ok"] is True
    assert db.get_note(note["id"]) is None
    assert db.get_task(t1["id"]) is None
    assert len(events_note) == 1
    assert len(events_task) == 1


def test_pin_note(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Quick ideas", "pinned": False})
    events = []
    bus.subscribe("note.updated", lambda data: events.append(data))

    res = execute_action("pin_note", {"note_id": note["id"], "pinned": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["note"]["pinned"] is True

    # Toggle pin without explicit bool
    res2 = execute_action("pin_note", {"note_id": note["id"]}, db, cfg, bus)
    assert res2["ok"] is True
    assert res2["note"]["pinned"] is False
    assert len(events) == 2


def test_pause_and_resume_activity(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("activity.live", lambda data: events.append(data))

    res = execute_action("pause_activity", {"paused": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["paused"] is True
    assert db.kv_get("activity_paused") == "1"

    res_resume = execute_action("pause_activity", {"paused": False}, db, cfg, bus)
    assert res_resume["ok"] is True
    assert res_resume["paused"] is False
    assert db.kv_get("activity_paused") == "0"
    assert len(events) == 2


def test_generate_daily_digest(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("dailylog.updated", lambda data: events.append(data))

    with patch("fleeting.services.dailylog.generate_daily_log") as mock_gen:
        async def fake_gen(db, cfg, day, *, rolling=False):
            return {"day": day, "summary_md": "Today's summary", "model": "mock"}
        mock_gen.side_effect = fake_gen

        res = execute_action("generate_daily_digest", {"day": "2026-10-03", "rolling": True}, db, cfg, bus)
        assert res["ok"] is True
        assert res["day"] == "2026-10-03"
        assert len(events) == 1
        assert events[0]["day"] == "2026-10-03"


def test_execute_action_unknown_tool(env):
    db, cfg, bus = env
    res = execute_action("nonexistent_tool", {}, db, cfg, bus)
    assert res["ok"] is False
    assert "unknown" in res["error"].lower()


def test_available_actions_structure():
    assert isinstance(AVAILABLE_ACTIONS, list)
    assert len(AVAILABLE_ACTIONS) == 9
    names = {a["name"] for a in AVAILABLE_ACTIONS}
    expected = {
        "delete_tasks",
        "create_task",
        "toggle_task",
        "update_task",
        "create_note",
        "delete_note",
        "pin_note",
        "generate_daily_digest",
        "pause_activity",
    }
    assert names == expected
    for action in AVAILABLE_ACTIONS:
        assert "name" in action
        assert "description" in action
        assert "parameters" in action
