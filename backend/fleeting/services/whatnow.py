"""The "what should I do now" query (#30 Today view, #33 next action).

The bundle deliberately builds both off one ranking: the Today view renders
the buckets this module returns, and the next-action card is just its top
rank. Scoring is a deterministic heuristic — priority, due urgency, whether
the estimate still fits the day, and a bonus when your *current* window
matches the task's repo or context — so it stays explainable and works
without the LLM.

All inputs are plain data (task dicts, a timestamp, the current window
title); nothing here touches request state, which is what makes it testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

_PRIORITY_SCORE = {"P1": 0, "P2": 10, "P3": 20}

# Due urgency spans a wider range than priority (0..30 vs 0..20), so:
# overdue debt beats today's work; today's P2 beats an undated P1; an
# undated P1 beats today's P3. Priority still breaks ties inside a bucket.
_FIT_PENALTY = 8
_ACTIVITY_BONUS = 5


def _blocked_ids(tasks: list[dict[str, Any]]) -> set[str]:
    """Tasks whose blockers are all done are not blocked."""
    by_id = {t["id"]: t for t in tasks}
    blocked: set[str] = set()
    for t in tasks:
        deps = t.get("blocked_by") or ""
        for dep in (p.strip() for p in deps.split(",") if p.strip()):
            dep_task = by_id.get(dep)
            if dep_task is None or not dep_task["done"]:
                blocked.add(t["id"])
                break
    return blocked


def _parents_with_open_children(tasks: list[dict[str, Any]]) -> set[str]:
    parents: set[str] = set()
    for t in tasks:
        if not t["done"] and t.get("parent_id"):
            parents.add(t["parent_id"])
    return parents


def _rank(t: dict[str, Any], today: str, minutes_left: int) -> tuple[int, ...]:
    if t.get("due_date"):
        if t["due_date"] < today:
            due_score = 0  # overdue debt first
        elif t["due_date"] == today:
            due_score = 8
        else:
            due_score = 30  # future work is planner material, not "now"
    else:
        due_score = 25  # undated: after dated work, before future
    est = t.get("estimate_min") or 0
    fit = _FIT_PENALTY if est and est > minutes_left else 0
    return (
        _PRIORITY_SCORE.get(t.get("priority", "P2"), 10) + due_score + fit,
        t.get("sort_order") or 0.0,
        t["created_at"],
        t["id"],
    )


def _activity_bonus(t: dict[str, Any], current_title: str | None) -> int:
    """Surface the task that matches what's on screen right now (#33).

    Window titles contain repo names ("fleeting — main.py — code") and often
    context-ish words, so a substring match on repo or context is a decent
    proxy for "this is the work I am already in".
    """
    if not current_title:
        return 0
    lowered = current_title.lower()
    for needle in (t.get("repo"), t.get("context")):
        if needle and str(needle).lower() in lowered:
            return _ACTIVITY_BONUS
    return 0


def build_today(
    tasks: list[dict[str, Any]],
    now: datetime,
    capacity_min: int,
    current_title: str | None = None,
) -> dict[str, Any]:
    """Bucket the day's work from a full task listing.

    `tasks` is db.list_tasks(status="all") output. Everything downstream —
    blocked detection, load, ranking — is computed here so the API layer
    stays a thin wrapper.
    """
    today = now.strftime("%Y-%m-%d")
    blocked = _blocked_ids(tasks)
    parents = _parents_with_open_children(tasks)

    open_inbox = [
        t for t in tasks
        if not t["done"] and t.get("list", "inbox") == "inbox" and not t.get("waiting_for")
    ]
    overdue = [t for t in open_inbox if t.get("due_date") and t["due_date"] < today]
    due_today = [t for t in open_inbox if t.get("due_date") == today]
    waiting = [
        t for t in tasks
        if not t["done"] and t.get("waiting_for") and t.get("list", "inbox") == "inbox"
    ]
    completed_today = [
        t for t in tasks
        if t["done"] and (t.get("completed_at") or "")[:10] == today
    ]

    def by_due_then_priority(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda t: (
                t.get("due_date") or "9999-12-31",
                _PRIORITY_SCORE.get(t.get("priority", "P2"), 10),
                t["created_at"],
            ),
        )

    overdue = by_due_then_priority(overdue)
    due_today = by_due_then_priority(due_today)

    # Day load (#32) counts leaves only — a parent and its children would
    # double-count the same work.
    workable = [t for t in overdue + due_today if t["id"] not in parents]
    estimated_min = sum(t.get("estimate_min") or 0 for t in workable)
    spent_min = sum(t.get("spent_min") or 0 for t in completed_today)

    # What's left of today's budget after the work already scheduled for it.
    # A candidate that cannot fit gets a fit penalty in _rank.
    undone_estimated = sum(t.get("estimate_min") or 0 for t in workable)
    minutes_left = max(0, capacity_min - spent_min - undone_estimated)

    # Next-action candidates: doable leaves, dated or not (#33). Dated work
    # older than a week out stays out of "what now" — that's planner material.
    horizon = (now + timedelta(days=7)).strftime("%Y-%m-%d")
    candidates = [
        t for t in open_inbox
        if t["id"] not in blocked
        and t["id"] not in parents
        and (t.get("due_date") is None or t["due_date"] <= horizon)
    ]
    candidates.sort(key=lambda t: (
        _rank(t, today, minutes_left)[0] - _activity_bonus(t, current_title),
        *_rank(t, today, minutes_left)[1:],
    ))

    return {
        "day": today,
        "overdue": overdue,
        "due_today": due_today,
        "waiting": waiting,
        "completed_today": completed_today,
        "next_action": candidates[0] if candidates else None,
        "up_next": candidates[1:6],
        "load": {
            "estimated_min": estimated_min,
            "spent_min": spent_min,
            "capacity_min": capacity_min,
        },
    }

def build_streaks(
    tasks: list[dict[str, Any]],
    now: datetime,
    days: int = 112,
) -> dict[str, Any]:
    """#39 completion streaks and a heatmap, from completed_at dates alone.

    A day counts as active when at least one task was completed on it. The
    current streak walks back from today; today not being done yet does not
    break it (the day isn't over), but a missed *yesterday* does.
    """
    today = now.strftime("%Y-%m-%d")
    counts: dict[str, int] = {}
    for t in tasks:
        if not t.get("done"):
            continue
        day = (t.get("completed_at") or "")[:10]
        if day:
            counts[day] = counts.get(day, 0) + 1

    # Heatmap cells, oldest first, one per day in the window.
    cells = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        cells.append({"day": day, "count": counts.get(day, 0)})

    # Current streak: consecutive active days ending today or yesterday.
    streak = 0
    cursor = now
    if counts.get(today, 0) == 0:
        cursor = cursor - timedelta(days=1)  # today is still open
    while counts.get(cursor.strftime("%Y-%m-%d"), 0) > 0:
        streak += 1
        cursor = cursor - timedelta(days=1)

    # Best streak anywhere in the window.
    best = run = 0
    prev: str | None = None
    for cell in cells:
        if cell["count"] > 0 and (prev is None or cell["day"] == _next_day(prev)):
            run += 1
        else:
            run = 1 if cell["count"] > 0 else 0
        best = max(best, run)
        prev = cell["day"]

    return {
        "current_streak": streak,
        "best_streak": best,
        "active_days": sum(1 for c in cells if c["count"] > 0),
        "cells": cells,
    }


def _next_day(day: str) -> str:
    return (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%d")
