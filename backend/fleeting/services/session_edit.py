"""#54 manual session editing.

The collector guesses; these are the corrections. Every change is written to
`session_edits` so a later bug report ("my split vanished") can be traced to
the edit that caused it rather than to the code that shipped since.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..db import Database, now_iso

log = logging.getLogger("fleeting.session_edit")


def _row(db: Database, session_id: int) -> dict:
    row = db.execute("SELECT * FROM activity WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise KeyError(f"session {session_id} not found")
    return dict(row)


def _record(db: Database, session_key: str, note: str) -> None:
    db.execute(
        "INSERT INTO session_edits (session_key, note, applied_at) VALUES (?, ?, ?)"
        " ON CONFLICT(session_key) DO UPDATE SET note=excluded.note,"
        " applied_at=excluded.applied_at",
        (session_key, note, now_iso()),
    )
    db.commit()


def annotate_session(db: Database, session_id: int, note: str) -> dict:
    """#334 say what a stretch was actually for; reports quote it back."""
    _row(db, session_id)
    clean = " ".join((note or "").split())[:400]
    db.execute("UPDATE activity SET note = ? WHERE id = ?", (clean, session_id))
    db.commit()
    if clean:
        _record(db, str(session_id), f"noted: {clean[:80]}")
    return _row(db, session_id)


def session_annotations(db: Database, day: str, limit: int = 50) -> list[dict]:
    """#334 the annotated sessions of a day, most recent first."""
    rows = db.execute(
        "SELECT id, app_class, title, first_seen, last_seen, seconds, note FROM activity"
        " WHERE day = ? AND note IS NOT NULL AND note != '' ORDER BY first_seen DESC LIMIT ?",
        (day, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def session_edits(db: Database, limit: int = 50) -> list[dict]:
    rows = db.execute(
        "SELECT session_key, note, applied_at FROM session_edits"
        " ORDER BY applied_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def relabel_session(db: Database, session_id: int, title: str) -> dict:
    """Give a session a name of your own. Time and app are untouched."""
    clean = " ".join((title or "").split())[:120]
    if not clean:
        raise ValueError("title must not be empty")
    _row(db, session_id)
    db.execute("UPDATE activity SET title = ? WHERE id = ?", (clean, session_id))
    db.commit()
    _record(db, str(session_id), f"relabelled to {clean!r}")
    return _row(db, session_id)


def delete_session(db: Database, session_id: int) -> bool:
    """Drop a session the collector invented (a phantom window, a stray poll)."""
    cur = db.execute("DELETE FROM activity WHERE id = ?", (session_id,))
    db.commit()
    if cur.rowcount:
        _record(db, str(session_id), "deleted")
        return True
    return False


def split_session(db: Database, session_id: int, at: str) -> tuple[int, int]:
    """Cut a session in two at `at`, splitting its seconds in proportion.

    Proportional rather than measured: the collector only knows the total, and
    inventing a per-minute split would be a guess dressed as a number.
    """
    row = _row(db, session_id)
    try:
        cut = datetime.fromisoformat(at)
    except (TypeError, ValueError) as exc:
        raise ValueError("`at` must be an ISO timestamp") from exc
    if cut.tzinfo is not None:
        # Stored times are local naive ISO; an offset-carrying value has to be
        # read in the same frame or the cut lands hours off.
        cut = cut.astimezone().replace(tzinfo=None)
    start = datetime.fromisoformat(row["first_seen"])
    end = datetime.fromisoformat(row["last_seen"])
    span = (end - start).total_seconds()
    total = int(row["seconds"] or 0)
    if span <= 0 or total < 2 or not (start < cut < end):
        raise ValueError("split point must be inside a session of at least 2 seconds")
    first_secs = int(round(total * (cut - start).total_seconds() / span))
    first_secs = max(1, min(first_secs, total - 1))

    cut_iso = cut.replace(microsecond=0).isoformat(timespec="seconds")
    db.execute(
        "UPDATE activity SET last_seen = ?, seconds = ? WHERE id = ?",
        (cut_iso, first_secs, session_id),
    )
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day,"
        " workspace, idle_secs, repo, branch, project, block_id, note)"
        " VALUES (:app_class, :title, :first_seen, :last_seen, :seconds, :day,"
        " :workspace, :idle_secs, :repo, :branch, :project, :block_id, :note)",
        {
            "app_class": row["app_class"],
            "title": row["title"],
            "first_seen": cut_iso,
            "last_seen": row["last_seen"],
            "seconds": total - first_secs,
            "day": row["day"],
            "workspace": row["workspace"],
            "idle_secs": row["idle_secs"],
            "repo": row["repo"],
            "branch": row["branch"],
            "project": row["project"],
            "block_id": row["block_id"],
            "note": row["note"],
        },
    )
    db.commit()
    new_id = int(cur.lastrowid)
    _record(db, str(session_id), f"split at {cut_iso} into {session_id}+{new_id}")
    return session_id, new_id


def merge_sessions(db: Database, ids: list[int]) -> int:
    """Fold sessions into the earliest one, summing their seconds."""
    wanted = sorted({int(i) for i in ids})
    if len(wanted) < 2:
        raise ValueError("merging needs at least two sessions")
    rows = [_row(db, i) for i in wanted]
    days = {r["day"] for r in rows}
    if len(days) > 1:
        raise ValueError("cannot merge sessions from different days")
    rows.sort(key=lambda r: r["first_seen"])
    keep, rest = rows[0], rows[1:]
    db.execute(
        "UPDATE activity SET first_seen = ?, last_seen = ?, seconds = ? WHERE id = ?",
        (
            keep["first_seen"],
            max(r["last_seen"] for r in rows),
            sum(int(r["seconds"] or 0) for r in rows),
            keep["id"],
        ),
    )
    for r in rest:
        db.execute("DELETE FROM activity WHERE id = ?", (r["id"],))
    db.commit()
    _record(db, str(keep["id"]), f"merged {len(rows)} sessions ({', '.join(str(i) for i in wanted)})")
    return int(keep["id"])