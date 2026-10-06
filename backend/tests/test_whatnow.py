"""Tests for the shared Today / next-action ranking (#30, #33, #32)."""

from __future__ import annotations

from datetime import datetime

from fleeting.services.whatnow import build_today

# A Wednesday afternoon, local.
NOW = datetime(2026, 10, 7, 14, 0, 0)
CAPACITY = 240


def make(**over) -> dict:
    base = {
        "id": over.get("id", over.get("text", "t").replace(" ", "-")),
        "text": over.get("text", "task"),
        "done": False,
        "priority": "P2",
        "due_date": None,
        "repo": None,
        "created_at": "2026-10-01T09:00:00+00:00",
        "completed_at": None,
        "parent_id": None,
        "blocked_by": None,
        "estimate_min": None,
        "spent_min": None,
        "list": "inbox",
        "context": None,
        "waiting_for": None,
        "follow_up_at": None,
        "recurrence": None,
        "sort_order": 0.0,
    }
    base.update(over)
    return base


def buckets(tasks, **kw):
    r = build_today(tasks, now=NOW, capacity_min=kw.pop("capacity", CAPACITY), **kw)
    return r


def test_buckets_exclude_someday_waiting_and_done():
    r = buckets([
        make(text="overdue", due_date="2026-10-05"),
        make(text="someday item", due_date="2026-10-05", list="someday"),
        make(text="waiting on bob", due_date="2026-10-05", waiting_for="bob"),
        make(text="done today", done=True, completed_at="2026-10-07T10:00:00+00:00"),
        make(text="done yesterday", done=True, completed_at="2026-10-06T10:00:00+00:00"),
    ])
    assert [t["text"] for t in r["overdue"]] == ["overdue"]
    assert [t["text"] for t in r["completed_today"]] == ["done today"]
    assert [t["text"] for t in r["waiting"]] == ["waiting on bob"]


def test_load_counts_leaves_only():
    r = buckets([
        make(text="parent", estimate_min=100, id="p", due_date="2026-10-07"),
        make(text="child", estimate_min=30, parent_id="p", id="c", due_date="2026-10-07"),
        make(text="other", estimate_min=60, due_date="2026-10-07"),
    ])
    # parent + child would double-count; only the leaf (30) plus other (60).
    assert r["load"]["estimated_min"] == 90
    assert r["load"]["capacity_min"] == CAPACITY


def test_next_action_prefers_overdue_p1_then_today():
    r = buckets([
        make(text="today p2", due_date="2026-10-07", priority="P2"),
        make(text="overdue p2", due_date="2026-10-05", priority="P2"),
        make(text="undated p1", priority="P1"),
    ])
    # overdue beats today beats undated, at equal priority.
    assert r["next_action"]["text"] == "overdue p2"
    texts = [t["text"] for t in r["up_next"]]
    assert texts[0] == "today p2"
    assert texts[1] == "undated p1"


def test_activity_bonus_surfaces_matching_repo():
    tasks = [
        make(text="other repo", due_date="2026-10-05", created_at="2026-10-01T09:00:00+00:00"),
        make(text="current repo", due_date="2026-10-05", repo="fleeting",
             created_at="2026-10-02T09:00:00+00:00"),
    ]
    # Without activity signal the older task leads; in the fleeting repo the
    # matching task jumps the queue (#33).
    assert buckets(tasks)["next_action"]["text"] == "other repo"
    r = buckets(tasks, current_title="code — fleeting — main.py")
    assert r["next_action"]["text"] == "current repo"


def test_blocked_tasks_are_not_suggested():
    r = buckets([
        make(text="blocker", due_date="2026-10-05", id="b"),
        make(text="blocked", due_date="2026-10-04", blocked_by="b", id="x"),
    ])
    assert r["next_action"]["text"] == "blocker"
    assert all(t["text"] != "blocked" for t in r["up_next"])

    # Blocker done → no longer blocked.
    r2 = buckets([
        make(text="blocker", due_date="2026-10-05", id="b", done=True,
             completed_at="2026-10-06T10:00:00+00:00"),
        make(text="blocked", due_date="2026-10-04", blocked_by="b", id="x"),
    ])
    assert r2["next_action"]["text"] == "blocked"


def test_task_too_big_for_remaining_day_ranks_lower():
    # Capacity nearly consumed by due-today work: the 3h candidate no longer fits.
    r = buckets([
        make(text="fills the day", due_date="2026-10-07", estimate_min=200, id="fill"),
        make(text="quick overdue", due_date="2026-10-05", estimate_min=15),
        make(text="big undated", estimate_min=180, priority="P1"),
    ], capacity=240)
    assert r["next_action"]["text"] == "quick overdue"
    assert "big undated" in [t["text"] for t in r["up_next"]]


def test_empty_day():
    r = buckets([])
    assert r["next_action"] is None
    assert r["up_next"] == []
    assert r["load"]["estimated_min"] == 0
