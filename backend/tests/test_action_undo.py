"""#103 undo: every assistant action the user confirmed can be taken back.

Confirmation alone only protects against the model doing something you didn't
want *at that moment*. Undo protects against the case where you approved it and
only afterwards realised it was wrong — which, for a delete, is the one that
actually costs you something.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.actions import execute_action, undo_action


@pytest.fixture
def env(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    return db, cfg, EventBus()


@pytest.mark.anyio
async def test_delete_note_can_be_undone(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Precious", "raw_text": "irreplaceable"})
    db.insert_task({"text": "child task", "note_id": note["id"]})

    res = await execute_action(
        "delete_note", {"note_id": note["id"], "confirm": True}, db, cfg, bus
    )
    assert res["ok"] is True
    assert db.get_note(note["id"]) is None

    undone = await undo_action(res["undo"], db, cfg, bus)
    assert undone["ok"] is True
    restored = db.get_note(note["id"])
    assert restored is not None
    assert restored["title"] == "Precious"
    assert [t["text"] for t in db.list_tasks(status="all")] == ["child task"]


@pytest.mark.anyio
async def test_delete_tasks_can_be_undone(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1", "priority": "P1"})
    t2 = db.insert_task({"text": "Task 2"})

    res = await execute_action(
        "delete_tasks", {"ids": [t1["id"], t2["id"]], "confirm": True}, db, cfg, bus
    )
    assert res["ok"] is True
    assert db.list_tasks(status="all") == []

    await undo_action(res["undo"], db, cfg, bus)
    assert {t["text"] for t in db.list_tasks(status="all")} == {"Task 1", "Task 2"}


@pytest.mark.anyio
async def test_toggle_task_can_be_undone(env):
    db, cfg, bus = env
    t = db.insert_task({"text": "Toggle me"})

    res = await execute_action("toggle_task", {"task_id": t["id"]}, db, cfg, bus)
    assert db.get_task(t["id"])["done"] == 1

    await undo_action(res["undo"], db, cfg, bus)
    assert db.get_task(t["id"])["done"] == 0


@pytest.mark.anyio
async def test_create_note_can_be_undone(env):
    db, cfg, bus = env
    res = await execute_action(
        "create_note", {"title": "Speculative", "content": "x"}, db, cfg, bus
    )
    note_id = res["note"]["id"]

    await undo_action(res["undo"], db, cfg, bus)
    assert db.get_note(note_id) is None


@pytest.mark.anyio
async def test_update_task_can_be_undone(env):
    db, cfg, bus = env
    t = db.insert_task({"text": "Original", "priority": "P2"})
    res = await execute_action(
        "update_task", {"task_id": t["id"], "text": "Rewritten"}, db, cfg, bus
    )

    await undo_action(res["undo"], db, cfg, bus)
    restored = db.get_task(t["id"])
    assert restored["text"] == "Original"


@pytest.mark.anyio
async def test_an_undo_can_only_be_used_once(env):
    db, cfg, bus = env
    note = db.insert_note({"title": "Once", "raw_text": "x"})
    res = await execute_action(
        "delete_note", {"note_id": note["id"], "confirm": True}, db, cfg, bus
    )

    assert (await undo_action(res["undo"], db, cfg, bus))["ok"] is True
    again = await undo_action(res["undo"], db, cfg, bus)
    assert again["ok"] is False
    assert "not found" in again["error"].lower()


@pytest.mark.anyio
async def test_undoing_an_unknown_token_fails_cleanly(env):
    db, cfg, bus = env
    res = await undo_action("nope", db, cfg, bus)
    assert res["ok"] is False
    assert res["error"]


def test_undo_endpoint_restores_a_deleted_task(client) -> None:
    """End to end through the assistant: confirm, delete, then take it back."""
    note = client.post("/api/capture/text", json={"text": "Undo me via the API"})
    task = client.post(
        "/api/tasks", json={"text": "Disposable task", "note_id": note.json()["id"]}
    ).json()
    task_id = task["id"]

    pending = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": f"delete task {task_id}"}]},
    ).json()["pending_action"]
    assert pending["tool"] == "delete_tasks"
    assert client.get(f"/api/tasks/{task_id}").status_code == 200

    done = client.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": f"delete task {task_id}"}], "confirm": True},
    ).json()
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    assert done["undo"]

    r = client.post("/api/assistant/undo", json={"undo": done["undo"]})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get(f"/api/tasks/{task_id}").status_code == 200


def test_undo_endpoint_rejects_a_used_token(client) -> None:
    note = client.post("/api/capture/text", json={"text": "Twice"})
    task = client.post(
        "/api/tasks", json={"text": "Once only", "note_id": note.json()["id"]}
    ).json()
    done = client.post(
        "/api/assistant/chat",
        json={
            "messages": [{"role": "user", "content": f"delete task {task['id']}"}],
            "confirm": True,
        },
    ).json()

    assert client.post("/api/assistant/undo", json={"undo": done["undo"]}).json()["ok"] is True
    assert client.post("/api/assistant/undo", json={"undo": done["undo"]}).json()["ok"] is False


@pytest.mark.anyio
async def test_pause_activity_can_be_undone(env):
    db, cfg, bus = env
    res = await execute_action("pause_activity", {"paused": True}, db, cfg, bus)
    assert db.kv_get("activity_paused") == "1"

    await undo_action(res["undo"], db, cfg, bus)
    assert db.kv_get("activity_paused") == "0"


@pytest.mark.anyio
async def test_undo_is_published_to_the_ui(env):
    """Restoring rows the UI just dropped must re-render them without a reload."""
    db, cfg, bus = env
    note = db.insert_note({"title": "Synced", "raw_text": "x"})
    res = await execute_action(
        "delete_note", {"note_id": note["id"], "confirm": True}, db, cfg, bus
    )

    seen: list[str] = []
    bus.subscribe("note.created", lambda data: seen.append(data["id"]))
    await undo_action(res["undo"], db, cfg, bus)
    assert seen == [note["id"]]
