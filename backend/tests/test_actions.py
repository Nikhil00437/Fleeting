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


@pytest.mark.anyio
async def test_delete_all_tasks(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1", "priority": "P1"})
    t2 = db.insert_task({"text": "Task 2", "priority": "P2"})
    assert len(db.list_tasks(status="all")) == 2

    events = []
    bus.subscribe("task.deleted", lambda data: events.append(data))

    res = await execute_action("delete_tasks", {"all": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["count"] == 2
    assert len(db.list_tasks(status="all")) == 0
    assert len(events) == 2


@pytest.mark.anyio
async def test_create_and_toggle_task(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("task.created", lambda data: events.append(("created", data)))
    bus.subscribe("task.updated", lambda data: events.append(("updated", data)))

    res = await execute_action("create_task", {"text": "Buy groceries", "priority": "P1"}, db, cfg, bus)
    assert res["ok"] is True
    task_id = res["task"]["id"]
    assert res["task"]["text"] == "Buy groceries"
    assert res["task"]["priority"] == "P1"

    toggle_res = await execute_action("toggle_task", {"task_id": task_id}, db, cfg, bus)
    assert toggle_res["ok"] is True
    assert toggle_res["task"]["done"] == 1


@pytest.mark.anyio
async def test_update_task(env):
    db, cfg, bus = env
    t = db.insert_task({"text": "Initial task", "priority": "P3"})
    events = []
    bus.subscribe("task.updated", lambda data: events.append(data))

    res = await execute_action(
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


@pytest.mark.anyio
async def test_delete_tasks_by_ids(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1"})
    t2 = db.insert_task({"text": "Task 2"})
    t3 = db.insert_task({"text": "Task 3"})
    assert len(db.list_tasks(status="all")) == 3

    events = []
    bus.subscribe("task.deleted", lambda data: events.append(data))

    res = await execute_action("delete_tasks", {"ids": [t1["id"], t3["id"]]}, db, cfg, bus)
    assert res["ok"] is True
    assert res["count"] == 2
    remaining = db.list_tasks(status="all")
    assert len(remaining) == 1
    assert remaining[0]["id"] == t2["id"]
    assert len(events) == 2


@pytest.mark.anyio
async def test_create_note_and_sync(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("note.created", lambda data: events.append(data))

    res = await execute_action(
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


@pytest.mark.anyio
async def test_delete_note_and_cascade(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Project plan", "raw_text": "Plan", "status": "done"})
    t1 = db.insert_task({"text": "Task under note", "note_id": note["id"]})

    events_note = []
    events_task = []
    bus.subscribe("note.deleted", lambda data: events_note.append(data))
    bus.subscribe("task.deleted", lambda data: events_task.append(data))

    res = await execute_action("delete_note", {"note_id": note["id"]}, db, cfg, bus)
    assert res["ok"] is True
    assert db.get_note(note["id"]) is None
    assert db.get_task(t1["id"]) is None
    assert len(events_note) == 1
    assert len(events_task) == 1


@pytest.mark.anyio
async def test_pin_note(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Quick ideas", "pinned": False})
    events = []
    bus.subscribe("note.updated", lambda data: events.append(data))

    res = await execute_action("pin_note", {"note_id": note["id"], "pinned": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["note"]["pinned"] is True

    # Toggle pin without explicit bool
    res2 = await execute_action("pin_note", {"note_id": note["id"]}, db, cfg, bus)
    assert res2["ok"] is True
    assert res2["note"]["pinned"] is False
    assert len(events) == 2


@pytest.mark.anyio
async def test_pause_and_resume_activity(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("activity.live", lambda data: events.append(data))

    res = await execute_action("pause_activity", {"paused": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["paused"] is True
    assert db.kv_get("activity_paused") == "1"

    res_resume = await execute_action("pause_activity", {"paused": False}, db, cfg, bus)
    assert res_resume["ok"] is True
    assert res_resume["paused"] is False
    assert db.kv_get("activity_paused") == "0"
    assert len(events) == 2


@pytest.mark.anyio
async def test_generate_daily_digest(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("dailylog.updated", lambda data: events.append(data))

    with patch("fleeting.services.dailylog.generate_daily_log") as mock_gen:
        async def fake_gen(db, cfg, day, *, rolling=False):
            return {"day": day, "summary_md": "Today's summary", "model": "mock"}
        mock_gen.side_effect = fake_gen

        res = await execute_action("generate_daily_digest", {"day": "2026-10-03", "rolling": True}, db, cfg, bus)
        assert res["ok"] is True
        assert res["day"] == "2026-10-03"
        assert len(events) == 1
        assert events[0]["day"] == "2026-10-03"


@pytest.mark.anyio
async def test_execute_action_unknown_tool(env):
    db, cfg, bus = env
    res = await execute_action("nonexistent_tool", {}, db, cfg, bus)
    assert res["ok"] is False
    assert "unknown" in res["error"].lower()


@pytest.mark.anyio
async def test_available_actions_structure():
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


@pytest.mark.anyio
async def test_create_note_tag_normalization(env):
    db, cfg, bus = env
    # 1. Comma-separated string with hashtags and spaces
    r1 = await execute_action("create_note", {"title": "Note 1", "content": "Text", "tags": "work, #urgent,  project "}, db, cfg, bus)
    assert r1["ok"] is True
    assert r1["note"]["tags"] == ["work", "urgent", "project"]

    # 2. Single string
    r2 = await execute_action("create_note", {"title": "Note 2", "content": "Text", "tags": "#solo"}, db, cfg, bus)
    assert r2["ok"] is True
    assert r2["note"]["tags"] == ["solo"]

    # 3. Tuple / non-list iterable
    r3 = await execute_action("create_note", {"title": "Note 3", "content": "Text", "tags": ("#t1", " t2 ")}, db, cfg, bus)
    assert r3["ok"] is True
    assert r3["note"]["tags"] == ["t1", "t2"]

    # 4. List with hashtags and spaces
    r4 = await execute_action("create_note", {"title": "Note 4", "content": "Text", "tags": ["#backend", " api "]}, db, cfg, bus)
    assert r4["ok"] is True
    assert r4["note"]["tags"] == ["backend", "api"]


@pytest.mark.anyio
async def test_pin_note_pinned_none(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Test Pin", "pinned": False})

    # Passing pinned=None should toggle (from False to True)
    res1 = await execute_action("pin_note", {"note_id": note["id"], "pinned": None}, db, cfg, bus)
    assert res1["ok"] is True
    assert res1["note"]["pinned"] is True

    # Passing pinned=None again should toggle (from True to False)
    res2 = await execute_action("pin_note", {"note_id": note["id"], "pinned": None}, db, cfg, bus)
    assert res2["ok"] is True
    assert res2["note"]["pinned"] is False


@pytest.mark.anyio
async def test_delete_tasks_batch_note_sync_deduplication(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Parent Note", "raw_text": "Content", "status": "done"})
    t1 = db.insert_task({"text": "T1", "note_id": note["id"]})
    t2 = db.insert_task({"text": "T2", "note_id": note["id"]})
    t3 = db.insert_task({"text": "T3", "note_id": note["id"]})

    with patch("fleeting.services.actions._sync_vault_and_notify_note") as mock_sync:
        res = await execute_action("delete_tasks", {"ids": [t1["id"], t2["id"], t3["id"]]}, db, cfg, bus)
        assert res["ok"] is True
        assert res["count"] == 3
        # Should be called once for note["id"], not 3 times
        assert mock_sync.call_count == 1
        assert mock_sync.call_args[0][0] == note["id"]


@pytest.mark.anyio
async def test_generate_daily_digest_screentime_milestone_sync(env):
    from datetime import datetime
    db, cfg, bus = env
    today = datetime.now().astimezone().strftime("%Y-%m-%d")

    # Add 4500 seconds (1.25 hours) of tracked activity today
    db.upsert_activity({
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T09:00:00",
        "last_seen": f"{today}T10:15:00",
        "seconds": 4500,
        "day": today,
    })
    db.commit()

    with patch("fleeting.services.dailylog.generate_daily_log") as mock_gen:
        async def fake_gen(db, cfg, day, *, rolling=False):
            return {"day": day, "summary_md": "Digest", "model": "mock"}
        mock_gen.side_effect = fake_gen

        res = await execute_action("generate_daily_digest", {"day": today, "rolling": True}, db, cfg, bus)
        assert res["ok"] is True
        # Check that screentime milestone KV was updated to 1 (4500 // 3600)
        assert db.kv_get(f"digest_screentime_hours_{today}") == "1"


@pytest.mark.anyio
async def test_event_bus_publish_mutation_safe():
    bus = EventBus()
    events = []

    def mutating_handler(data):
        events.append(data)
        # Unsubscribe during publish loop
        bus.unsubscribe(mutating_handler, "test.event")
        # Add another handler during publish loop
        bus.subscribe("test.event", lambda d: events.append("added"))

    bus.subscribe("test.event", mutating_handler)
    # Publishing should not raise RuntimeError: dictionary/list modified during iteration
    bus.publish("test.event", "payload-1")
    assert len(events) == 1

