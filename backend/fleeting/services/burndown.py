"""#423 backlog burndown chart for unprocessed items and open tasks."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING

from . import calendar_svc

if TYPE_CHECKING:
    from ..db import Database


def get_backlog_burndown(db: Database, *, days: int = 30) -> dict:
    """Calculate the daily burndown of backlog items (tasks & pending captures).

    Tracks additions vs resolutions per day and reconstructs the running backlog
    trajectory leading up to today, along with resolution velocity and projected days
    to backlog zero.
    """
    days = max(3, min(days, 180))
    today_dt = calendar_svc.today()
    start_dt = today_dt - timedelta(days=days - 1)

    # 1. Fetch tasks
    task_rows = db.execute(
        """
        SELECT id, text, done, created_at, completed_at
        FROM tasks
        """
    ).fetchall()

    tasks_added_by_day: dict[str, int] = defaultdict(int)
    tasks_done_by_day: dict[str, int] = defaultdict(int)
    current_open_tasks = 0

    for r in task_rows:
        if not r["done"]:
            current_open_tasks += 1
        c_day = calendar_svc.date_tag(r["created_at"])
        if c_day:
            tasks_added_by_day[c_day] += 1
        if r["done"] and r["completed_at"]:
            d_day = calendar_svc.date_tag(r["completed_at"])
            if d_day:
                tasks_done_by_day[d_day] += 1

    # 2. Fetch notes (captures)
    # Open captures: status = 'pending'
    # Completed/processed captures: status in ('processed', 'done')
    note_rows = db.execute(
        """
        SELECT id, status, created_at, updated_at
        FROM notes
        WHERE trashed_at IS NULL
        """
    ).fetchall()

    captures_added_by_day: dict[str, int] = defaultdict(int)
    captures_done_by_day: dict[str, int] = defaultdict(int)
    current_pending_captures = 0

    for r in note_rows:
        st = r["status"]
        if st == "pending":
            current_pending_captures += 1
        c_day = calendar_svc.date_tag(r["created_at"])
        if c_day:
            captures_added_by_day[c_day] += 1
        if st in ("processed", "done"):
            # If status is processed/done, use updated_at or created_at as resolution day
            p_day = calendar_svc.date_tag(r["updated_at"] or r["created_at"])
            if p_day:
                captures_done_by_day[p_day] += 1

    current_backlog = current_open_tasks + current_pending_captures

    # Build date list from start_dt to today_dt
    date_list = [
        (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(days)
    ]

    # Calculate net change for each day in range
    daily_stats = []
    total_resolved_in_window = 0

    for d in date_list:
        t_add = tasks_added_by_day[d]
        t_done = tasks_done_by_day[d]
        c_add = captures_added_by_day[d]
        c_done = captures_done_by_day[d]

        added = t_add + c_add
        resolved = t_done + c_done
        total_resolved_in_window += resolved

        daily_stats.append({
            "day": d,
            "tasks_added": t_add,
            "tasks_completed": t_done,
            "captures_added": c_add,
            "captures_resolved": c_done,
            "added": added,
            "resolved": resolved,
            "net": added - resolved,
        })

    # Reconstruct historical running backlog working backwards from current_backlog at today
    # backlog_at_end_of_day[i] = backlog_at_end_of_day[i-1] + net[i]
    # backlog_at_end_of_today = current_backlog
    backlog_trajectory = [0] * days
    running = current_backlog
    for idx in range(days - 1, -1, -1):
        backlog_trajectory[idx] = max(0, running)
        running -= daily_stats[idx]["net"]

    start_backlog = backlog_trajectory[0]
    peak_backlog = max(backlog_trajectory) if backlog_trajectory else 0

    # Calculate ideal burndown line from start_backlog (or peak) down to 0 at today
    ideal_baseline = max(start_backlog, peak_backlog)
    series = []
    for idx, stat in enumerate(daily_stats):
        ideal_val = round(max(0.0, ideal_baseline * (1.0 - (idx / max(1, days - 1)))), 1)
        series.append({
            **stat,
            "open_backlog": backlog_trajectory[idx],
            "ideal_burndown": ideal_val,
        })

    # Velocity: average daily resolution rate
    avg_daily_resolved = round(total_resolved_in_window / max(1, days), 2)
    days_to_zero = (
        round(current_backlog / avg_daily_resolved, 1)
        if avg_daily_resolved > 0 and current_backlog > 0
        else (0.0 if current_backlog == 0 else None)
    )

    projected_date = None
    if days_to_zero is not None and days_to_zero > 0:
        proj_dt = today_dt + timedelta(days=round(days_to_zero))
        projected_date = proj_dt.strftime("%Y-%m-%d")

    return {
        "window_days": days,
        "current_backlog": current_backlog,
        "current_open_tasks": current_open_tasks,
        "current_pending_captures": current_pending_captures,
        "total_added": sum(s["added"] for s in series),
        "total_resolved": total_resolved_in_window,
        "avg_daily_resolved": avg_daily_resolved,
        "days_to_zero": days_to_zero,
        "projected_date": projected_date,
        "series": series,
    }
