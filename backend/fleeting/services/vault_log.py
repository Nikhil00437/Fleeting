"""#113/#118/#120: the vault sync log.

A log, not a mirror of current state, because the question the filesystem cannot
answer on its own is: **what did we last write, and has the file changed since?**

A `stat()` says the file is newer than the row. It cannot say whether the file
holds *our* content or the user's edit on top of it. That distinction is the whole
basis of conflict detection — without a recorded hash of the bytes we wrote,
every file touched in Obsidian looks like a conflict, every conflict looks like a
change to accept, and the user's actual work gets overwritten by "resolving" it.

The log is append-only and capped, so it is a record rather than a second copy of
the vault. Each entry carries both hashes: by the time anyone resolves a
conflict, the "before" is otherwise unrecoverable.
"""

from __future__ import annotations

from typing import Any

# Enough to cover the files anyone has open in another editor, at a rate that
# keeps the table from growing without bound. A conflict resolved after a month
# of edits is not a conflict, it is a decision.
LOG_CAP = 2000


def _now() -> str:
    from ..db import now_iso

    return now_iso()


def record(
    db: Any,
    note_id: str,
    path: str,
    direction: str,
    hash_before: str | None,
    hash_after: str | None,
    conflict: bool = False,
) -> None:
    """Append one sync event. Never raises — a logging failure must not stop the
    write it is logging."""
    try:
        db.conn.execute(
            "INSERT INTO vault_sync_log (note_id, path, direction, hash_before, hash_after, conflict, at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (note_id, path, direction, hash_before, hash_after, 1 if conflict else 0, _now()),
        )
        db.prune_vault_sync_log(LOG_CAP)
        db.commit()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("fleeting.vault").warning(
            "could not record vault sync for %s", note_id, exc_info=True
        )


def last_write(db: Any, note_id: str) -> dict[str, Any] | None:
    """The most recent *write* for a note — what we believe the file holds."""
    row = db.execute(
        "SELECT * FROM vault_sync_log WHERE note_id = ? AND direction = 'write'"
        " ORDER BY id DESC LIMIT 1",
        (note_id,),
    ).fetchone()
    return dict(row) if row else None


def history(db: Any, note_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM vault_sync_log WHERE note_id = ? ORDER BY id DESC LIMIT ?",
        (note_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def conflicts(db: Any, limit: int = 200) -> list[dict[str, Any]]:
    """Every recorded conflict, newest first.

    `limit` because this feeds a list a person reads, and an endpoint that
    returns every conflicting file turns itself into a vault listing.
    """
    rows = db.execute(
        "SELECT * FROM vault_sync_log WHERE conflict = 1 ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def prune(db: Any, cap: int = LOG_CAP) -> int:
    """Drop the oldest beyond `cap`. Idempotent; returns how many went."""
    return db.prune_vault_sync_log(cap)