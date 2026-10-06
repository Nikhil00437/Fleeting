"""#284 weekly planner, #442 capacity gauge."""

from __future__ import annotations

from datetime import date, datetime

from fleeting.services.planner import plan_week

# A Monday.
NOW = datetime(2026, 10, 5, 9, 0)


def make(**over) -> dict:
    base = {
        "id": over.get("text", "t").replace(" ", "-"),
        "text": over.get("text", "task"),
        "done": False,
        "priority": over.get("priority", "P2"),
        "due_date": over.get("due_date"),
        "estimate_min": over.get("estimate_min", 30),
        "list": over.get("list", "inbox"),
        "context": None,
        "waiting_for": None,
        "parent_id": None,
        "blocked_by": None,
    }
    base.update(over)
    return base


def day(plan, date_str):
    return next(d for d in plan["days"] if d["day"] == date_str)


def test_weekend_days_have_no_capacity():
    plan = plan_week([make(text="a")], now=NOW, capacity_min=240)
    sat = day(plan, "2026-10-10")
    sun = day(plan, "2026-10-11")
    assert sat["capacity_min"] == 0
    assert sun["capacity_min"] == 0
    assert sat["task_ids"] == []


def test_holidays_have_no_capacity():
    plan = plan_week(
        [make(text="a")], now=NOW, capacity_min=240, holidays={date(2026, 10, 6)}
    )
    assert day(plan, "2026-10-06")["capacity_min"] == 0


def test_undated_work_packs_into_the_earliest_day_with_room():
    plan = plan_week([make(text="a", estimate_min=60)], now=NOW, capacity_min=240)
    assert day(plan, "2026-10-05")["task_ids"] == ["a"]
    assert day(plan, "2026-10-05")["planned_min"] == 60


def test_dated_work_is_charged_to_its_due_day_first():
    plan = plan_week([make(text="b", due_date="2026-10-07", estimate_min=90)], now=NOW, capacity_min=240)
    assert day(plan, "2026-10-07")["planned_min"] == 90
    assert day(plan, "2026-10-07")["task_ids"] == ["b"]


def test_an_already_full_day_takes_no_new_work():
    tasks = [
        make(text="dated", due_date="2026-10-06", estimate_min=240),
        make(text="filler", estimate_min=60),
    ]
    plan = plan_week(tasks, now=NOW, capacity_min=240)
    assert day(plan, "2026-10-06")["planned_min"] == 240
    # Filler packs into the earliest day with room (Monday), never onto the
    # already-full Tuesday.
    assert day(plan, "2026-10-06")["task_ids"] == ["dated"]
    assert "filler" in day(plan, "2026-10-05")["task_ids"]


def test_oversized_work_spills_rather_than_overbooking():
    tasks = [make(text="big", estimate_min=10_000)]
    plan = plan_week(tasks, now=NOW, capacity_min=240)
    assert plan["unscheduled"] == ["big"]
    assert all(d["planned_min"] <= d["capacity_min"] for d in plan["days"])


def test_unestimated_work_is_charged_a_nominal_thirty_minutes():
    tasks = [make(text="no-estimate", estimate_min=None)]
    plan = plan_week(tasks, now=NOW, capacity_min=240)
    assert day(plan, "2026-10-05")["planned_min"] == 30


def test_totals_drive_the_capacity_gauge():
    plan = plan_week(
        [make(text="a", estimate_min=60), make(text="b", estimate_min=60)],
        now=NOW,
        capacity_min=240,
    )
    # Five working days in a Mon-Sun week.
    assert plan["totals"]["capacity_min"] == 1200
    assert plan["totals"]["planned_min"] == 120
    assert plan["totals"]["over_capacity"] is False
    assert plan["totals"]["utilization"] == 0.1


def test_blocked_and_waiting_work_is_not_planned():
    tasks = [
        make(text="blocked", blocked_by="other"),
        make(text="waiting", waiting_for="Sam"),
        make(text="someday", list="someday"),
    ]
    plan = plan_week(tasks, now=NOW, capacity_min=240)
    placed = [tid for d in plan["days"] for tid in d["task_ids"]]
    assert "blocked" not in placed
    assert "waiting" not in placed
    assert "someday" not in placed