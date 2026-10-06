"""#27: the boot reminder's due-task summary."""

from __future__ import annotations

from datetime import datetime, timedelta

from fleeting.db import Database
from fleeting.services.task_reminders import due_task_summary


def test_summary_counts_and_orders_by_debt(tmp_path):
    db = Database(tmp_path / "remind.db")
    db.migrate()
    today = datetime.now().astimezone()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    db.insert_task({"text": "overdue old", "due_date": yesterday, "priority": "P2"})
    db.insert_task({"text": "overdue worse", "due_date": yesterday, "priority": "P1"})
    db.insert_task({"text": "due today", "due_date": today.strftime("%Y-%m-%d")})
    db.insert_task({"text": "not due yet", "due_date": tomorrow})
    db.insert_task({"text": "no date"})
    db.insert_task({"text": "already done", "due_date": yesterday})
    done = next(t for t in db.list_tasks(status="open") if t["text"] == "already done")
    db.toggle_task(done["id"])

    s = due_task_summary(db)
    assert s["total"] == 3
    assert s["overdue"] == 2
    assert s["today"] == 1
    # Most overdue first, and P1 before P2 within the same day.
    assert s["top"][0] == "overdue worse"
    assert "not due yet" not in s["top"]


def test_summary_skips_someday_and_waiting(tmp_path):
    db = Database(tmp_path / "remind2.db")
    db.migrate()
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")

    db.insert_task({"text": "someday overdue", "due_date": yesterday, "list": "someday"})
    db.insert_task({"text": "waiting on bob", "due_date": yesterday, "waiting_for": "bob"})

    s = due_task_summary(db)
    assert s["total"] == 0
