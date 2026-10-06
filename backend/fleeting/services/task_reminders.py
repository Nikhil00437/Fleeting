"""#27: desktop reminders for due tasks.

One boot-time nudge rather than a midnight job: the machine is often asleep
at midnight (same reasoning as the daily-report backfill), and a reminder is
only useful when someone is actually at the keyboard. Someday/maybe items and
waiting-for items never nag — they are deliberately out of the daily view.
"""

from __future__ import annotations

from typing import Any

from ..db import Database, datetime_now_local


def due_task_summary(db: Database, limit: int = 50) -> dict[str, Any]:
    """Open tasks that are overdue or due today, for the boot notification."""
    today = datetime_now_local().strftime("%Y-%m-%d")
    due: list[dict[str, Any]] = []
    for bucket in ("overdue", "today"):
        for t in db.list_tasks(status="open", due=bucket, limit=limit):
            if t.get("list", "inbox") != "inbox" or t.get("waiting_for"):
                continue
            due.append(t)

    # Oldest first: the most overdue debt leads the notification.
    due.sort(key=lambda t: (t.get("due_date") or today, t.get("priority", "P2")))
    texts = [t["text"] for t in due]
    return {
        "total": len(texts),
        "overdue": sum(1 for t in due if (t.get("due_date") or "") < today),
        "today": sum(1 for t in due if t.get("due_date") == today),
        "top": texts[:3],
    }
