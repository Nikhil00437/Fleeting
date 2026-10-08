"""#339 one feed for a day: what you did, what you finished, what you wrote.

Notes and tasks carry UTC timestamps while sessions carry local wall time, so
each is bucketed by its own frame: a note captured at 19:30 UTC belongs to that
evening in the user's day, which is what the ribbon shows.
"""

from __future__ import annotations

from datetime import datetime

from ..db import Database
from .calendar_svc import date_tag


def day_events(
    db: Database, day: str, *, kinds: tuple[str, ...] = ("session", "task", "note"), limit: int = 200
) -> list[dict]:
    """Everything that happened on `day`, in chronological order."""
    events: list[dict] = []

    if "session" in kinds:
        rows = db.execute(
            "SELECT id, app_class, title, first_seen, seconds FROM activity"
            " WHERE day = ? AND seconds >= 1 ORDER BY first_seen LIMIT ?",
            (day, limit),
        ).fetchall()
        events += [
            {
                "kind": "session",
                "id": r["id"],
                "at": r["first_seen"],
                "label": r["app_class"],
                "detail": r["title"] or "",
                "seconds": r["seconds"],
            }
            for r in rows
        ]

    if "task" in kinds:
        rows = db.execute(
            "SELECT id, text, done, completed_at FROM tasks"
            " WHERE completed_at IS NOT NULL ORDER BY completed_at LIMIT ?",
            (limit,),
        ).fetchall()
        events += [
            {
                "kind": "task",
                "id": r["id"],
                "at": r["completed_at"],
                "label": r["text"],
                "detail": "",
                "done": bool(r["done"]),
            }
            for r in rows
            if date_tag(r["completed_at"]) == day
        ]

    if "note" in kinds:
        rows = db.execute(
            "SELECT id, title, type, created_at FROM notes"
            " WHERE trashed_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        events += [
            {
                "kind": "note",
                "id": r["id"],
                "at": r["created_at"],
                "label": r["title"] or "Untitled",
                "detail": r["type"],
            }
            for r in rows
            if date_tag(r["created_at"]) == day
        ]

    events.sort(key=lambda e: e["at"])
    return events[:limit]


def minutes_into_day(at: str) -> int:
    """Position on the 24-hour ribbon, in minutes."""
    try:
        dt = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return 0
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.hour * 60 + dt.minute