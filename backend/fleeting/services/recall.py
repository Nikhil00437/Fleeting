"""Resurfacing: random old note, this day last year, weekly time capsule.

All three are the same question — "notes from *then*, not from *now*" — with a
different notion of *then*, so they share one query shape.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ..db import Database, _row_to_note


def week_seed(now: datetime | None = None) -> int:
    """A stable-per-ISO-week integer, so the capsule doesn't change daily."""
    return (now or datetime.now(timezone.utc)).isocalendar()[1]


def recall_random_old(
    db: Database,
    *,
    older_than_days: int = 90,
    limit: int = 5,
    seed: int | None = None,
) -> list[dict]:
    """#46: any note old enough to have fallen out of sight.

    `seed` makes the draw reproducible (the UI passes a per-render key so a
    re-render doesn't reshuffle); omit it for a fresh surprise every call.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    rows = db.execute(
        "SELECT * FROM notes WHERE archived = 0 AND trashed_at IS NULL "
        "AND created_at < ? ORDER BY created_at DESC LIMIT 200",
        (cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),),
    ).fetchall()
    notes = [_row_to_note(r) for r in rows]
    random.Random(seed).shuffle(notes)
    return notes[:limit]


def recall_this_day(db: Database, *, today: datetime | None = None, limit: int = 3) -> list[dict]:
    """#47: notes captured on this month/day in an *earlier* year, newest first.

    Matched on the stored ``YYYY-MM-DD`` prefix, so 29 Feb only matches a
    29 Feb and never drifts onto 1 Mar.
    """
    now = today or datetime.now(timezone.utc)
    rows = db.execute(
        "SELECT * FROM notes WHERE archived = 0 AND trashed_at IS NULL "
        "AND substr(created_at, 6, 5) = ? AND substr(created_at, 1, 4) < ? "
        "ORDER BY created_at DESC LIMIT ?",
        (now.strftime("%m-%d"), now.strftime("%Y"), limit),
    ).fetchall()
    return [_row_to_note(r) for r in rows]


def recall_time_capsule(db: Database, *, now: datetime | None = None) -> dict | None:
    """#297: one note from >=365 days ago, stable for the whole ISO week."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=365)
    rows = db.execute(
        "SELECT * FROM notes WHERE archived = 0 AND trashed_at IS NULL "
        "AND created_at < ? ORDER BY created_at DESC LIMIT 200",
        (cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),),
    ).fetchall()
    notes = [_row_to_note(r) for r in rows]
    if not notes:
        return None
    notes.sort(key=lambda n: n["id"])  # id order is stable across queries
    return notes[week_seed(now) % len(notes)]