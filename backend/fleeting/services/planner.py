"""Weekly planning: distribute work across days, and gauge the week (#284, #442).

The planner takes the open, doable tasks and packs them into the coming week
by *available* capacity per day. Two rules make it defensible without a
calendar integration:

1. Days already holding dated work are charged for it first. If Tuesday
   already carries 90 minutes of due-dated tasks, the planner only fills the
   remaining `daily_capacity_min - already_planned` with new work.
2. Weekends and configured holidays have zero capacity (#444), so they never
   appear in the plan.

Undated work is packed in ranking order (the same urgency/fit sense
whatnow._rank uses) rather than round-robin, so the week's hardest item lands
while there is still room for it. Tasks that fit nowhere spill into
`unscheduled` — the planner never silently overbooks a day.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .calendar_svc import is_workday

# How far ahead the planner looks. A week of capacity is the unit; anything
# further out belongs to the someday list, not a plan.
_PLAN_DAYS = 7


def plan_week(
    tasks: list[dict[str, Any]],
    now: datetime,
    capacity_min: int,
    holidays: set[date] | None = None,
    start: date | None = None,
) -> dict[str, Any]:
    """Pack open tasks into the next `_PLAN_DAYS` days.

    `tasks` is db.list_tasks(status="open") output. Returns
    {week_start, days: [{day, capacity_min, planned_min, task_ids}],
    unscheduled: [id], totals: {...}}.
    """
    hol = holidays or set()
    today = now.date()
    week_start = start or (today - timedelta(days=today.weekday()))

    days: list[dict[str, Any]] = []
    for i in range(_PLAN_DAYS):
        day = week_start + timedelta(days=i)
        days.append({
            "day": day.strftime("%Y-%m-%d"),
            "workday": is_workday(day, hol),
            "capacity_min": capacity_min if is_workday(day, hol) else 0,
            "planned_min": 0,
            "task_ids": [],
        })

    # Blocked, waiting-on-someone and someday work is not plannable — it has
    # no day it can be done on until the blocker clears.
    candidates = [
        t for t in tasks
        if not t.get("blocked_by") and not t.get("waiting_for") and t.get("list", "inbox") == "inbox"
    ]

    def day_by(date_str: str) -> dict[str, Any] | None:
        return next((d for d in days if d["day"] == date_str), None)

    # 1) Charge work that already has a due date inside the week.
    carry = [t for t in candidates if t.get("due_date") and day_by(t["due_date"]) is not None]
    for t in sorted(carry, key=lambda x: (x["due_date"], _priority_rank(x))):
        slot = day_by(t["due_date"])
        assert slot is not None
        slot["task_ids"].append(t["id"])
        slot["planned_min"] += _estimate(t)

    # 2) Fill the remaining capacity with undated work, ranked.
    undated = [t for t in candidates if not t.get("due_date")]
    undated.sort(key=lambda x: (x.get("due_date") or "9999-12-31", _priority_rank(x)))
    unscheduled: list[str] = []
    for t in undated:
        est = _estimate(t)
        placed = False
        for slot in days:
            if slot["planned_min"] + est <= slot["capacity_min"]:
                slot["task_ids"].append(t["id"])
                slot["planned_min"] += est
                placed = True
                break
        if not placed:
            unscheduled.append(t["id"])

    total_capacity = sum(d["capacity_min"] for d in days)
    total_planned = sum(d["planned_min"] for d in days)
    return {
        "week_start": week_start.strftime("%Y-%m-%d"),
        "days": days,
        "unscheduled": unscheduled,
        "totals": {
            "capacity_min": total_capacity,
            "planned_min": total_planned,
            "over_capacity": total_planned > total_capacity,
            "utilization": round(total_planned / total_capacity, 2) if total_capacity else 0.0,
        },
    }


def _priority_rank(t: dict[str, Any]) -> int:
    return {"P1": 0, "P2": 1, "P3": 2}.get(t.get("priority", "P2"), 1)


def _estimate(t: dict[str, Any]) -> int:
    """Unestimated work is charged a nominal 30m so it cannot fill a week
    for free — the planner's job is to surface that it has no estimate."""
    return int(t.get("estimate_min") or 30)
