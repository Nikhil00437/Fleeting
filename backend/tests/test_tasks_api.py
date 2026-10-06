"""Tests for dedicated /api/tasks REST API and SSE event broadcasting."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from fleeting.models import TaskOut


def _capture_events(client, monkeypatch):
    """Capture all EventBus publish calls for assertion."""
    events = []
    original_publish = client.app.state.st.bus.publish

    def mock_publish(event_type, data):
        events.append({"type": event_type, "data": data})
        original_publish(event_type, data)

    monkeypatch.setattr(client.app.state.st.bus, "publish", mock_publish)
    return events


def test_post_task_with_existing_note(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    st = client.app.state.st
    note = st.db.insert_note({"title": "Project Meeting", "action_items": []})

    resp = client.post(
        "/api/tasks",
        json={
            "note_id": note["id"],
            "text": "Refactor router endpoints",
            "priority": "P1",
            "due_date": "2026-10-15",
            "repo": "fleeting",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"]
    assert data["note_id"] == note["id"]
    assert data["note_title"] == "Project Meeting"
    assert data["text"] == "Refactor router endpoints"
    assert data["priority"] == "P1"
    assert data["due_date"] == "2026-10-15"
    assert data["repo"] == "fleeting"
    assert data["done"] is False
    assert data["completed_at"] is None

    # Verify event published
    created_events = [e for e in events if e["type"] == "task.created"]
    assert len(created_events) == 1
    assert created_events[0]["data"]["id"] == data["id"]
    assert created_events[0]["data"]["text"] == "Refactor router endpoints"

    # Verify parent note synchronized
    updated_note = st.db.get_note(note["id"])
    assert any(item["id"] == data["id"] for item in updated_note["action_items"])


def test_post_task_standalone_creates_inbox_note(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    resp = client.post(
        "/api/tasks",
        json={
            "text": "Quick standalone task without note",
            "priority": "P2",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"]
    assert data["note_id"]
    assert data["text"] == "Quick standalone task without note"

    # Verify note in DB
    note = client.app.state.st.db.get_note(data["note_id"])
    assert note is not None
    assert "Inbox" in note["title"]

    # Verify event published
    assert any(e["type"] == "task.created" and e["data"]["id"] == data["id"] for e in events)


def test_post_task_invalid_inputs(client):
    # Empty text
    r = client.post("/api/tasks", json={"text": ""})
    assert r.status_code == 422

    # Invalid priority
    r = client.post("/api/tasks", json={"text": "Valid text", "priority": "P9"})
    assert r.status_code == 422

    # Invalid date format
    r = client.post("/api/tasks", json={"text": "Valid text", "due_date": "next-tuesday"})
    assert r.status_code == 422

    # Non-existent note_id
    r = client.post("/api/tasks", json={"text": "Valid text", "note_id": "nonexistent_note_id"})
    assert r.status_code == 404


def test_get_task_by_id(client):
    st = client.app.state.st
    note = st.db.insert_note({"title": "Note For Get"})
    task = st.db.insert_task({
        "note_id": note["id"],
        "text": "Fetchable task",
        "priority": "P3",
    })

    # Success
    r = client.get(f"/api/tasks/{task['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == task["id"]
    assert body["text"] == "Fetchable task"
    assert body["priority"] == "P3"
    assert body["note_title"] == "Note For Get"

    # 404 for missing
    r_missing = client.get("/api/tasks/not_found_123")
    assert r_missing.status_code == 404


def test_get_tasks_filtering(client):
    st = client.app.state.st
    n1 = st.db.insert_note({"title": "Frontend App"})
    n2 = st.db.insert_note({"title": "Backend API"})

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    next_week = (datetime.now().astimezone() + timedelta(days=4)).strftime("%Y-%m-%d")

    t1 = st.db.insert_task({
        "note_id": n1["id"],
        "text": "Fix button alignment",
        "priority": "P1",
        "repo": "frontend",
        "due_date": today,
    })
    t2 = st.db.insert_task({
        "note_id": n1["id"],
        "text": "Upgrade react packages",
        "priority": "P2",
        "repo": "frontend",
        "due_date": yesterday,  # overdue
    })
    t3 = st.db.insert_task({
        "note_id": n2["id"],
        "text": "Write database indices",
        "priority": "P3",
        "repo": "backend",
        "due_date": next_week,
    })
    t4 = st.db.insert_task({
        "note_id": n2["id"],
        "text": "Refactor auth middleware",
        "priority": "P1",
        "repo": "backend",
        "due_date": None,
    })
    # Mark t4 as done
    st.db.toggle_task(t4["id"])

    # 1. Default status=open
    r = client.get("/api/tasks")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3
    assert {i["id"] for i in items} == {t1["id"], t2["id"], t3["id"]}

    # 2. status=done
    r_done = client.get("/api/tasks", params={"status": "done"})
    assert r_done.status_code == 200
    assert len(r_done.json()) == 1
    assert r_done.json()[0]["id"] == t4["id"]

    # 3. status=all
    r_all = client.get("/api/tasks", params={"status": "all"})
    assert r_all.status_code == 200
    assert len(r_all.json()) == 4

    # 4. Backward compatibility include_done=True
    r_inc = client.get("/api/tasks", params={"include_done": True})
    assert r_inc.status_code == 200
    assert len(r_inc.json()) == 4

    # 5. Filter by priority
    r_p1 = client.get("/api/tasks", params={"status": "all", "priority": "P1"})
    assert len(r_p1.json()) == 2
    assert {i["id"] for i in r_p1.json()} == {t1["id"], t4["id"]}

    # 6. Filter by repo
    r_fe = client.get("/api/tasks", params={"repo": "frontend"})
    assert len(r_fe.json()) == 2
    assert {i["id"] for i in r_fe.json()} == {t1["id"], t2["id"]}

    # 7. Filter by due date: overdue
    r_overdue = client.get("/api/tasks", params={"due": "overdue"})
    assert len(r_overdue.json()) == 1
    assert r_overdue.json()[0]["id"] == t2["id"]

    # 8. Filter by due date: today
    r_today = client.get("/api/tasks", params={"due": "today"})
    assert len(r_today.json()) == 1
    assert r_today.json()[0]["id"] == t1["id"]

    # 9. Filter by due date: week
    r_week = client.get("/api/tasks", params={"due": "week"})
    assert len(r_week.json()) == 2
    assert {i["id"] for i in r_week.json()} == {t1["id"], t3["id"]}

    # 10. Filter by due date: nodate
    r_nodate = client.get("/api/tasks", params={"status": "all", "due": "nodate"})
    assert len(r_nodate.json()) == 1
    assert r_nodate.json()[0]["id"] == t4["id"]

    # 11. Search query q
    r_search = client.get("/api/tasks", params={"status": "all", "q": "database"})
    assert len(r_search.json()) == 1
    assert r_search.json()[0]["id"] == t3["id"]

    # 12. Search query by note title
    r_search_note = client.get("/api/tasks", params={"status": "all", "q": "Frontend App"})
    assert len(r_search_note.json()) == 2

    # 13. Pagination limit and offset
    page1 = client.get("/api/tasks", params={"status": "all", "limit": 2, "offset": 0}).json()
    page2 = client.get("/api/tasks", params={"status": "all", "limit": 2, "offset": 2}).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert {p["id"] for p in page1}.isdisjoint({p["id"] for p in page2})


def test_patch_task(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    st = client.app.state.st
    note = st.db.insert_note({"title": "Note Patch Test"})
    task = st.db.insert_task({"note_id": note["id"], "text": "Original text", "priority": "P2"})

    # Update text, priority, due_date, repo
    resp = client.patch(
        f"/api/tasks/{task['id']}",
        json={
            "text": "Updated text",
            "priority": "P1",
            "due_date": "2026-11-01",
            "repo": "fleeting",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task["id"]
    assert data["text"] == "Updated text"
    assert data["priority"] == "P1"
    assert data["due_date"] == "2026-11-01"
    assert data["repo"] == "fleeting"

    # Verify event published
    patch_events = [e for e in events if e["type"] == "task.updated"]
    assert len(patch_events) >= 1
    assert patch_events[-1]["data"]["id"] == task["id"]
    assert patch_events[-1]["data"]["priority"] == "P1"

    # Verify parent note synchronized
    updated_note = st.db.get_note(note["id"])
    item = next(it for it in updated_note["action_items"] if it["id"] == task["id"])
    assert item["text"] == "Updated text"
    assert item["priority"] == "P1"

    # Patch non-existent task returns 404
    r_404 = client.patch("/api/tasks/missing_task_id", json={"priority": "P3"})
    assert r_404.status_code == 404


def test_toggle_task(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    st = client.app.state.st
    note = st.db.insert_note({"title": "Toggle Note"})
    task = st.db.insert_task({"note_id": note["id"], "text": "Toggle me", "done": False})

    # 1. Toggle open -> done
    r1 = client.post(f"/api/tasks/{task['id']}/toggle")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["done"] is True
    assert data1["completed_at"] is not None

    # Check SSE event
    toggle_events = [e for e in events if e["type"] == "task.updated"]
    assert len(toggle_events) >= 1
    assert toggle_events[-1]["data"]["done"] is True

    # Note synchronized
    n_sync1 = st.db.get_note(note["id"])
    assert any(it["id"] == task["id"] and it["done"] is True for it in n_sync1["action_items"])

    # 2. Toggle done -> open
    r2 = client.post(f"/api/tasks/{task['id']}/toggle")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["done"] is False
    assert data2["completed_at"] is None

    n_sync2 = st.db.get_note(note["id"])
    assert any(it["id"] == task["id"] and it["done"] is False for it in n_sync2["action_items"])

    # 3. 404 for missing task
    r_missing = client.post("/api/tasks/missing_task_id/toggle")
    assert r_missing.status_code == 404


def test_delete_task(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    st = client.app.state.st
    note = st.db.insert_note({"title": "Delete Note"})
    task = st.db.insert_task({"note_id": note["id"], "text": "To be deleted"})

    # Delete task
    r = client.delete(f"/api/tasks/{task['id']}")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": task["id"]}

    # Verify task deleted from DB
    assert st.db.get_task(task["id"]) is None
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404

    # Verify event published
    del_events = [e for e in events if e["type"] == "task.deleted"]
    assert len(del_events) == 1
    assert del_events[0]["data"] == {"id": task["id"], "note_id": note["id"]}

    # Verify removed from note.action_items
    updated_note = st.db.get_note(note["id"])
    assert not any(it["id"] == task["id"] for it in updated_note["action_items"])

    # 404 on deleting non-existent task
    r_404 = client.delete("/api/tasks/already_deleted_or_missing")
    assert r_404.status_code == 404


def test_get_tasks_stats(client):
    st = client.app.state.st
    note = st.db.insert_note({"title": "Stats Note"})

    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    yesterday = (datetime.now().astimezone() - timedelta(days=2)).strftime("%Y-%m-%d")

    st.db.insert_task({"note_id": note["id"], "text": "T1", "priority": "P1", "due_date": today})
    st.db.insert_task({"note_id": note["id"], "text": "T2", "priority": "P2", "due_date": yesterday})
    t3 = st.db.insert_task({"note_id": note["id"], "text": "T3", "priority": "P3"})
    st.db.toggle_task(t3["id"])

    r = client.get("/api/tasks/stats")
    assert r.status_code == 200
    stats = r.json()
    assert stats["total"] == 3
    assert stats["open"] == 2
    assert stats["done"] == 1
    assert stats["completion_rate"] == round(1 / 3, 2)
    assert stats["by_priority"]["P1"] == 1
    assert stats["by_priority"]["P2"] == 1
    assert stats["by_priority"]["P3"] == 0
    assert stats["overdue"] == 1
    assert stats["due_today"] == 1


def test_get_tasks_repos(client, tmp_path):
    st = client.app.state.st
    note = st.db.insert_note({"title": "Repos Note"})

    # Insert tasks with repo tags
    st.db.insert_task({"note_id": note["id"], "text": "T1", "repo": "fleeting"})
    st.db.insert_task({"note_id": note["id"], "text": "T2", "repo": "fleeting"})
    st.db.insert_task({"note_id": note["id"], "text": "T3", "repo": "dotfiles"})

    # Create local git repo under watch_dirs
    watch_dir = tmp_path / "projects"
    watch_dir.mkdir()
    local_repo = watch_dir / "my-service"
    local_repo.mkdir()
    (local_repo / ".git").mkdir()

    # Also make fleeting exist locally
    fleeting_local = watch_dir / "fleeting"
    fleeting_local.mkdir()
    (fleeting_local / ".git").mkdir()

    st.cfg.activity.watch_dirs = str(watch_dir)

    r = client.get("/api/tasks/repos")
    assert r.status_code == 200
    repos = r.json()
    assert isinstance(repos, list)

    repo_names = [rp["name"] for rp in repos]
    assert "fleeting" in repo_names
    assert "dotfiles" in repo_names
    assert "my-service" in repo_names

    # Check fleeting: exists both in DB and locally
    fleeting_entry = next(rp for rp in repos if rp["name"] == "fleeting")
    assert fleeting_entry["task_count"] == 2
    assert fleeting_entry["path"] == str(fleeting_local.resolve())

    # Check dotfiles: exists in DB, not locally
    dotfiles_entry = next(rp for rp in repos if rp["name"] == "dotfiles")
    assert dotfiles_entry["task_count"] == 1
    assert dotfiles_entry["path"] is None

    # Check my-service: exists locally, 0 tasks in DB
    service_entry = next(rp for rp in repos if rp["name"] == "my-service")
    assert service_entry["task_count"] == 0
    assert service_entry["path"] == str(local_repo.resolve())


# ---- 0.5 planning fields ----------------------------------------------------


def test_task_planning_fields_roundtrip(client):
    st = client.app.state.st
    parent = st.db.insert_task({"text": "Parent task"})

    resp = client.post(
        "/api/tasks",
        json={
            "text": "Plan sprint",
            "parent_id": parent["id"],
            "estimate_min": 120,
            "list": "someday",
            "context": "@computer",
            "waiting_for": "design review",
            "follow_up_at": "2026-10-20",
            "recurrence": "FREQ=WEEKLY;BYDAY=MO",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["parent_id"] == parent["id"]
    assert data["estimate_min"] == 120
    assert data["list"] == "someday"
    assert data["context"] == "computer"
    assert data["waiting_for"] == "design review"
    assert data["follow_up_at"] == "2026-10-20"
    assert data["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"

    patch = client.patch(f"/api/tasks/{data['id']}", json={"estimate_min": 30, "context": "@errands"})
    assert patch.status_code == 200
    assert patch.json()["estimate_min"] == 30
    assert patch.json()["context"] == "errands"


def test_task_blocked_by_as_list(client):
    """blocked_by accepts an array of ids from the UI and stores CSV."""
    st = client.app.state.st
    a = st.db.insert_task({"text": "A"})
    b = st.db.insert_task({"text": "B"})

    resp = client.post("/api/tasks", json={"text": "Blocked", "blocked_by": [a["id"], b["id"]]})
    assert resp.status_code == 200
    assert resp.json()["blocked_by"] == f"{a['id']},{b['id']}"


def test_task_invalid_parent_is_400(client):
    resp = client.post("/api/tasks", json={"text": "Orphan", "parent_id": "missing"})
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]


def test_task_dependency_cycle_is_400(client):
    st = client.app.state.st
    a = st.db.insert_task({"text": "A"})
    b = st.db.insert_task({"text": "B", "blocked_by": a["id"]})

    resp = client.patch(f"/api/tasks/{a['id']}", json={"blocked_by": [b["id"]]})
    assert resp.status_code == 400
    assert "cycle" in resp.json()["detail"]


def test_task_planning_field_validation(client):
    resp = client.post("/api/tasks", json={"text": "Bad minutes", "estimate_min": -10})
    assert resp.status_code == 422

    resp = client.post("/api/tasks", json={"text": "Bad date", "follow_up_at": "next tuesday"})
    assert resp.status_code == 422

    resp = client.post("/api/tasks", json={"text": "Bad list", "list": "later"})
    assert resp.status_code == 422


def test_quick_add_parses_natural_language(client):
    resp = client.post("/api/tasks/quick-add", json={"text": "call dentist tomorrow 3pm #health"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["text"] == "call dentist 3pm"
    assert data["task"]["due_date"] == (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert data["task"]["repo"] == "health"
    assert data["parsed"]["due_date"] == data["task"]["due_date"]


def test_quick_add_explicit_fields_beat_parsed(client):
    resp = client.post(
        "/api/tasks/quick-add",
        json={"text": "call dentist tomorrow", "due_date": "2026-11-01", "priority": "P1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["due_date"] == "2026-11-01"
    assert data["task"]["priority"] == "P1"


def test_quick_add_plain_text_stays_verbatim(client):
    resp = client.post("/api/tasks/quick-add", json={"text": "a plain thought"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["text"] == "a plain thought"
    assert data["task"]["due_date"] is None


def test_today_endpoint(client):
    st = client.app.state.st
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    st.db.insert_task({"text": "overdue thing", "due_date": yesterday})
    st.db.insert_task({"text": "due now", "due_date": today, "estimate_min": 30})
    st.db.insert_task({"text": "future", "due_date": "2027-01-01"})

    resp = client.get("/api/tasks/today")
    assert resp.status_code == 200
    data = resp.json()
    assert data["day"] == today
    assert [t["text"] for t in data["overdue"]] == ["overdue thing"]
    assert [t["text"] for t in data["due_today"]] == ["due now"]
    assert data["next_action"]["text"] in ("overdue thing", "due now")
    assert data["load"]["estimated_min"] == 30
    assert data["load"]["capacity_min"] > 0


def test_completing_recurring_task_spawns_next(client, monkeypatch):
    events = _capture_events(client, monkeypatch)
    resp = client.post(
        "/api/tasks",
        json={"text": "weekly review", "recurrence": "FREQ=WEEKLY", "due_date": "2026-10-06"},
    )
    assert resp.status_code == 200
    task_id = resp.json()["id"]

    toggled = client.post(f"/api/tasks/{task_id}/toggle")
    assert toggled.status_code == 200
    assert toggled.json()["done"] is True

    # The next occurrence exists and is open, with a due date at or past the old one.
    tasks = client.get("/api/tasks", params={"status": "all"}).json()
    occurrences = [t for t in tasks if t["text"] == "weekly review"]
    assert len(occurrences) == 2
    next_occ = next(t for t in occurrences if t["id"] != task_id)
    assert next_occ["done"] is False
    assert next_occ["recurrence"] == "FREQ=WEEKLY"
    assert next_occ["due_date"] >= "2026-10-06"
    assert any(e["type"] == "task.created" for e in events)

    # Un-completing does not spawn a third occurrence.
    client.post(f"/api/tasks/{task_id}/toggle")
    tasks = client.get("/api/tasks", params={"status": "all"}).json()
    assert len([t for t in tasks if t["text"] == "weekly review"]) == 2


def test_patch_done_true_spawns_recurring_next(client):
    resp = client.post("/api/tasks", json={"text": "daily stretch", "recurrence": "FREQ=DAILY"})
    task_id = resp.json()["id"]
    client.patch(f"/api/tasks/{task_id}", json={"done": True})
    tasks = client.get("/api/tasks", params={"status": "all"}).json()
    assert len([t for t in tasks if t["text"] == "daily stretch"]) == 2
