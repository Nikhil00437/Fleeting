"""#136: forget the last N minutes.

This is the feature a local-first notes app exists for, and the one place where
"are you sure?" is not enough on its own. A confirm dialog makes you read; a
panic button is for the moment you are not going to read carefully. So:

- **A preview with titles, not ids.** You cannot confirm "delete 4 rows". You
  can confirm the four things you dictated once you can see what they are.
- **Only what was *created* in the window goes.** A note you had for six months
  and edited five minutes ago is not "the last ten minutes", even though it is
  inside the window by timestamp. Destroying a long-lived note to protect the
  last ten minutes is a worse failure than leaving one stray edit behind, and a
  panic button that can do it will eventually do it.

Tasks and activity in the window go too: a task extracted from a note you just
dictated, or a window title captured while it was on screen, is part of what you
are trying to forget. Leaving those behind would make the feature worse than
useless.

Reuses `services/bulk.py`, so "are you sure" means the same thing here as it
does for every other destructive call, and every one of them is audited (#140).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database
from .bulk import preview, require_confirm

log = logging.getLogger("fleeting.forget")

# Past a week this is not "panic", it is "wipe my history", and the preview
# list stops being something anyone read.
MAX_MINUTES = 60 * 24 * 7
# No SAMPLE_LIMIT here: `bulk.preview()` already caps the sample list, and a
# second constant that never wins is one more number to keep in step.


def _since(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _notes_in_window(db: Database, since: str) -> list[dict]:
    return list(
        db.execute(
            "SELECT id, title, raw_text, created_at FROM notes"
            " WHERE created_at >= ? AND trashed_at IS NULL"
            " ORDER BY created_at DESC LIMIT 500",
            (since,),
        ).fetchall()
    )


def _count(db: Database, sql: str, params: tuple) -> int:
    return int(db.execute(sql, params).fetchone()["c"])


def window_preview(db: Database, minutes: int) -> dict[str, Any]:
    """What the next `minutes` contain. Never mutates."""
    minutes = max(1, min(int(minutes), MAX_MINUTES))
    since = _since(minutes)
    notes = _notes_in_window(db, since)
    tasks = _count(db, "SELECT COUNT(*) c FROM tasks WHERE created_at >= ?", (since,))
    activity = _count(
        db,
        "SELECT COUNT(*) c FROM activity WHERE first_seen >= ?",
        (since,),
    )
    return preview(
        len(notes) + tasks + activity,
        [
            {
                "id": r["id"],
                "title": r["title"] or (r["raw_text"] or "")[:60],
                "created_at": r["created_at"],
            }
            for r in notes
        ],
        notes=len(notes),
        tasks=tasks,
        activity=activity,
        minutes=minutes,
    )


def forget(
    db: Database,
    minutes: int,
    confirm: bool,
    bus: Any = None,
    on_note_delete=None,
) -> dict[str, Any]:
    """Delete the window, if confirmed. Returns `{"ok": True}` when there is
    nothing to forget — no prompt for an empty room."""
    detail = window_preview(db, minutes)
    require_confirm(None, confirm, detail)
    minutes = detail["minutes"]
    if detail["notes"] == 0 and detail["tasks"] == 0 and detail["activity"] == 0:
        return {"ok": True, "forgotten": {"notes": 0, "tasks": 0, "activity": 0}, "detail": detail}

    since = _since(minutes)
    notes = _notes_in_window(db, since)

    forgotten_tasks = _count(db, "SELECT COUNT(*) c FROM tasks WHERE created_at >= ?", (since,))
    forgotten_activity = _count(db, "SELECT COUNT(*) c FROM activity WHERE first_seen >= ?", (since,))

    # Activity and tasks first: tasks reference notes with ON DELETE CASCADE, so
    # the notes would take them anyway — counting them separately first is what
    # makes the audit entry add up.
    db.conn.execute("DELETE FROM activity WHERE first_seen >= ?", (since,))
    db.conn.execute("DELETE FROM tasks WHERE created_at >= ?", (since,))

    forgotten_notes = 0
    for row in notes:
        if on_note_delete is not None:
            on_note_delete(row)
        db.delete_note(row["id"])
        forgotten_notes += 1
    db.commit()

    if bus is not None:
        for row in notes:
            bus.publish("note.deleted", {"id": row["id"]})
        bus.publish("privacy.forget", {"minutes": minutes, "notes": forgotten_notes})

    db.record_audit(
        "privacy.forget",
        f"last {minutes}m",
        {"minutes": minutes, "notes": forgotten_notes, "tasks": forgotten_tasks, "activity": forgotten_activity},
    )
    log.info("forgot last %dm: %d notes, %d tasks, %d activity", minutes, forgotten_notes, forgotten_tasks, forgotten_activity)
    return {
        "ok": True,
        "forgotten": {
            "notes": forgotten_notes,
            "tasks": forgotten_tasks,
            "activity": forgotten_activity,
        },
        "detail": detail,
    }