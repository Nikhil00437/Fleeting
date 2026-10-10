"""#110: a nightly "what did I forget?" nudge for open loops.

The feature is one question asked at one moment of the day: of the things you
said you'd do and have not, which are still yours?

Everything here is deterministic and reads trackers that already exist — #169's
unfinished threads and the task table. No model call: a nudge that invents its
own items is worse than no nudge, because the one thing it says is "I have
been thinking about your work" and a hallucinated item makes that a lie.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .. import notify
from .unfinished_threads import get_unfinished_threads

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.nudges")

# A hundred overdue tasks is not a nudge, it is a wall. The count reported is
# what actually matched so "showing 10" never reads as "that is all of them".
DEFAULT_LIMIT = 5


def _overdue_tasks(db: Database, day: str, *, skip_texts: set[str]) -> list[dict[str, Any]]:
    """Open tasks whose due date has passed.

    Separate from #169's stale-task rule, which goes by *age*. A task you gave
    a date to and then let pass is a stronger signal of forgetting than one
    that merely has not been closed yet.

    Sensitive notes (#26) are filtered in SQL rather than in Python so there is
    one gate, not two that can drift: a nudge is a notification, which the OS
    and any notification centre can render, so a task's wording counts as note
    content and must not leave the app.
    """
    rows = db.execute(
        """
        SELECT t.* FROM tasks t
        LEFT JOIN notes n ON n.id = t.note_id
        WHERE t.done = 0
          AND t.due_date IS NOT NULL
          AND TRIM(t.due_date) != ''
          AND t.due_date < ?
          AND (t.note_id IS NULL OR (n.archived = 0 AND n.trashed_at IS NULL))
          AND (t.note_id IS NULL OR n.sensitive = 0)
        ORDER BY t.due_date ASC
        """,
        (day,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        task = dict(row)
        text = str(task.get("text") or "")
        if text.lower() in skip_texts:
            continue
        out.append(
            {
                "kind": "task",
                "id": f"task_{task['id']}",
                "task_id": str(task["id"]),
                "text": text,
                "due_date": str(task.get("due_date") or ""),
            }
        )
    return out


def nightly_nudge(db: Database, cfg: Config, *, day: str, limit: int = DEFAULT_LIMIT) -> dict:
    """The open loops still outstanding on `day`, oldest debt first.

    `day` is passed in rather than read from the clock: the caller decides what
    "tonight" means, and a test can then pin it. A task due *today* is not
    overdue — it is not forgotten at 9am.
    """
    threads = [
        {
            "kind": "thread",
            "id": t["id"],
            "text": t.get("text") or "",
            "age_days": t.get("age_days") or 0,
            "task_id": t.get("task_id"),
        }
        for t in get_unfinished_threads(db)
    ]
    # #169 already lists stale tasks as threads. Repeating them as overdue
    # items would show the same line twice in one nudge, so a task whose text
    # is already a thread is skipped rather than shown again.
    already = {t["text"].strip().lower() for t in threads}

    items = threads + _overdue_tasks(db, day, skip_texts=already)

    # Most-neglected first: a thread's age is days, a task's is how far past
    # its due date it is, so both reduce to "how long has this been owed".
    def _owed(item: dict[str, Any]) -> int:
        if item["kind"] == "thread":
            return int(item.get("age_days") or 0)
        return _days_between(str(item.get("due_date") or day), day)

    items.sort(key=_owed, reverse=True)

    return {
        "day": day,
        "count": len(items),
        "items": items[: max(1, int(limit))],
    }


def _days_between(earlier: str, later: str) -> int:
    from datetime import date

    try:
        return (date.fromisoformat(later) - date.fromisoformat(earlier)).days
    except Exception:
        return 0


def should_notify(db: Database, cfg: Config, *, day: str) -> bool:
    """True when tonight's nudge should be sent, marking the day as used.

    Opt-in, like #416's stale-contact list: an unrequested midnight
    notification is how an app gets muted wholesale.

    A night with nothing to say does *not* consume the day, so adding an
    overdue task later the same evening still gets a nudge.
    """
    if not cfg.notifications.nightly_nudge:
        return False
    key = f"nudge_sent:{day}"
    if db.kv_get(key):
        return False
    if nightly_nudge(db, cfg, day=day)["count"] == 0:
        return False
    db.kv_set(key, "1")
    return True


def notify_text(nudge: dict[str, Any]) -> tuple[str, str]:
    """The (summary, body) pair for the desktop notification."""
    count = int(nudge.get("count") or 0)
    if not count:
        return ("Nothing outstanding", "No open loops tonight.")
    noun = "loop" if count == 1 else "loops"
    first = (nudge.get("items") or [{}])[0].get("text", "")
    return (
        f"{count} open {noun} still yours",
        f"Oldest: {first}" if first else "",
    )


def nightly_notify(db: Database, cfg: Any, bus: Any, *, day: str) -> bool:
    """Send tonight's nudge, once. Called from the day-rollover job.

    Returns whether anything was sent. Never raises: this runs inside the
    midnight job that also writes the daily report, and a missing notification
    daemon must not take the report down with it.
    """
    if not should_notify(db, cfg, day=day):
        return False
    try:
        nudge = nightly_nudge(db, cfg, day=day)
        summary, body = notify_text(nudge)
    except Exception:
        log.exception("could not build the nightly nudge for %s", day)
        return False

    if cfg.notifications.desktop:
        try:
            notify.send(summary, body)
        except Exception:
            # The desktop channel and the in-app one are independent. A missing
            # notification daemon must not also swallow the in-app nudge, which
            # is the one the user can actually act on.
            log.warning("desktop notification failed for %s", day, exc_info=True)

    try:
        bus.publish("nudge.ready", nudge)
    except Exception:
        log.warning("could not publish the nightly nudge for %s", day, exc_info=True)
    return True