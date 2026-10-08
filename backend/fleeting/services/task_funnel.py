"""#250 task funnel: captured, planned, started, completed."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database


def get_task_funnel(db: Database, *, days: int | None = None) -> dict:
    """Calculate the task pipeline conversion funnel.

    Stages:
    1. Captured: all tasks recorded
    2. Planned: tasks that have a due date, an estimate, a custom list (not 'inbox'), or were finished
    3. Started: tasks that have logged focus time (spent_min > 0) or are finished
    4. Completed: tasks marked done (done = 1)
    """
    params: list = []
    where_sql = ""
    if days is not None and days > 0:
        where_sql = "WHERE created_at >= datetime('now', ?)"
        params.append(f"-{days} days")

    rows = db.execute(
        f"""
        SELECT id, text, done, priority, due_date, estimate_min, spent_min, list, created_at, completed_at
        FROM tasks
        {where_sql}
        ORDER BY created_at DESC
        """,
        params,
    ).fetchall()

    captured_items = []
    planned_items = []
    started_items = []
    completed_items = []

    by_priority: dict[str, dict] = {
        "P1": {"captured": 0, "planned": 0, "started": 0, "completed": 0},
        "P2": {"captured": 0, "planned": 0, "started": 0, "completed": 0},
        "P3": {"captured": 0, "planned": 0, "started": 0, "completed": 0},
    }

    for r in rows:
        prio = r["priority"] or "P2"
        p_stats = by_priority.setdefault(prio, {"captured": 0, "planned": 0, "started": 0, "completed": 0})

        captured_items.append(r)
        p_stats["captured"] += 1

        is_done = bool(r["done"])
        has_plan = (
            bool(r["due_date"])
            or (r["estimate_min"] is not None and r["estimate_min"] > 0)
            or (r["list"] and r["list"] != "inbox")
            or is_done
        )
        has_started = (r["spent_min"] is not None and r["spent_min"] > 0) or is_done

        if has_plan:
            planned_items.append(r)
            p_stats["planned"] += 1

        if has_started:
            started_items.append(r)
            p_stats["started"] += 1

        if is_done:
            completed_items.append(r)
            p_stats["completed"] += 1

    total_c = len(captured_items)
    total_p = len(planned_items)
    total_s = len(started_items)
    total_d = len(completed_items)

    def _stage_dict(stage_id: str, name: str, count: int, prev_count: int) -> dict:
        pct_of_captured = round((count / total_c) * 100.0, 1) if total_c > 0 else 0.0
        dropoff_pct = round(((prev_count - count) / prev_count) * 100.0, 1) if prev_count > 0 else 0.0
        return {
            "stage": stage_id,
            "name": name,
            "count": count,
            "pct_of_captured": pct_of_captured,
            "dropoff_pct": max(0.0, dropoff_pct),
        }

    stages = [
        _stage_dict("captured", "Captured", total_c, total_c),
        _stage_dict("planned", "Planned", total_p, total_c),
        _stage_dict("started", "Started", total_s, total_p),
        _stage_dict("completed", "Completed", total_d, total_s),
    ]

    return {
        "window_days": days,
        "total_tasks": total_c,
        "stages": stages,
        "by_priority": by_priority,
    }
