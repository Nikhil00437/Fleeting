"""Tests for recurring tasks (#28): RRULE advancement and spawn-on-complete."""

from __future__ import annotations

from datetime import date

from fleeting.db import Database
from fleeting.services.recurrence import next_anchor, next_due


def test_daily_and_interval():
    base = date(2026, 10, 6)
    assert next_due("FREQ=DAILY", base) == date(2026, 10, 7)
    assert next_due("FREQ=DAILY;INTERVAL=3", base) == date(2026, 10, 9)


def test_weekly():
    base = date(2026, 10, 6)  # Tuesday
    assert next_due("FREQ=WEEKLY", base) == date(2026, 10, 13)
    assert next_due("FREQ=WEEKLY;INTERVAL=2", base) == date(2026, 10, 20)


def test_weekly_byday_picks_next_matching_weekday():
    base = date(2026, 10, 6)  # Tuesday
    # MO,WE from Tuesday: tomorrow is Wednesday, not next Monday.
    assert next_due("FREQ=WEEKLY;BYDAY=MO,WE", base) == date(2026, 10, 7)
    # MO,FR from Tuesday: Friday first, then the next Monday.
    assert next_due("FREQ=WEEKLY;BYDAY=MO,FR", base) == date(2026, 10, 9)
    assert next_due("FREQ=WEEKLY;BYDAY=MO,FR", date(2026, 10, 9)) == date(2026, 10, 12)


def test_monthly_and_yearly_clamp():
    assert next_due("FREQ=MONTHLY", date(2026, 1, 31)) == date(2026, 2, 28)
    assert next_due("FREQ=MONTHLY;INTERVAL=3", date(2026, 10, 6)) == date(2027, 1, 6)
    assert next_due("FREQ=YEARLY", date(2024, 2, 29)) == date(2025, 2, 28)


def test_next_anchor_uses_today_when_overdue():
    today = date(2026, 10, 6)
    # Completing an overdue weekly task schedules from today, not the past.
    assert next_anchor("2026-09-01", today) == today
    # Completing early keeps the rhythm anchored on the original due date.
    assert next_anchor("2026-10-20", today) == date(2026, 10, 20)
    assert next_anchor(None, today) == today


def test_toggle_spawns_next_occurrence():
    db = Database(":memory:")
    db.migrate()
    t = db.insert_task({
        "text": "water the plants",
        "recurrence": "FREQ=WEEKLY;BYDAY=TU",
        "due_date": "2026-10-06",
    })
    done = db.toggle_task(t["id"])
    assert done["done"] is True

    spawned = db.spawn_next_occurrence(t["id"])
    assert spawned is not None
    assert spawned["id"] != t["id"]
    assert spawned["done"] is False
    assert spawned["text"] == "water the plants"
    assert spawned["recurrence"] == "FREQ=WEEKLY;BYDAY=TU"
    # Next Tuesday after the (current) anchor — never in the past.
    assert spawned["due_date"] >= "2026-10-06"
    assert spawned["spent_min"] is None

    # Non-recurring or un-completed tasks never spawn.
    plain = db.insert_task({"text": "one off"})
    db.toggle_task(plain["id"])
    assert db.spawn_next_occurrence(plain["id"]) is None
