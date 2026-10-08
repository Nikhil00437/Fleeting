"""#337 "you were away for 2h — what happened?".

A gap is only worth asking about if it is long enough to matter, and only
worth surfacing if the user was awake to have spent it. The caller supplies the
day bounds so "a gap at 3am" is never proposed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..db import Database

DEFAULT_MIN_MINUTES = 45
# A local day, minus the hours nobody would fill in a journal entry for.
DEFAULT_BOUNDS = ("07:00:00", "23:30:00")


def day_gaps(
    db: Database,
    day: str,
    *,
    min_minutes: int = DEFAULT_MIN_MINUTES,
    day_bounds: tuple[str, str] | None = DEFAULT_BOUNDS,
) -> list[dict]:
    """Untracked stretches on a day, longest first."""
    rows = db.execute(
        "SELECT first_seen, last_seen FROM activity WHERE day = ? AND seconds >= 1"
        " ORDER BY first_seen",
        (day,),
    ).fetchall()
    start_bound, end_bound = day_bounds or DEFAULT_BOUNDS
    day_start = datetime.fromisoformat(f"{day}T{start_bound}")
    day_end = datetime.fromisoformat(f"{day}T{end_bound}")

    gaps: list[dict] = []
    cursor = day_start
    for row in rows:
        try:
            seen_start = datetime.fromisoformat(row["first_seen"])
            seen_end = datetime.fromisoformat(row["last_seen"])
        except ValueError:
            continue
        if seen_start > cursor:
            gaps.append(_gap(cursor, seen_start))
        cursor = max(cursor, seen_end)
    if day_end > cursor:
        gaps.append(_gap(cursor, day_end))

    kept = [g for g in gaps if g["minutes"] >= min_minutes]
    kept.sort(key=lambda g: -g["minutes"])
    return kept


def _gap(start: datetime, end: datetime) -> dict:
    minutes = int((end - start).total_seconds() // 60)
    return {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"), "minutes": minutes}


def gap_summary(gaps: list[dict]) -> str:
    """One line for a toast or a nudge, empty when there is nothing to ask."""
    if not gaps:
        return ""
    total = sum(g["minutes"] for g in gaps)
    if len(gaps) == 1:
        return f"You were away {human(total)} — what happened?"
    return f"{len(gaps)} untracked stretches, {human(total)} in total — what happened?"


def human(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    if not hours:
        return f"{mins}m"
    return f"{hours}h{mins:02d}m" if mins else f"{hours}h"


def fill_gap(gaps: list[dict], at: str, minutes: int, note: str) -> dict | None:
    """Fold a written answer into the record as a synthetic session.

    The window starts at the time they named and is truncated to the gap it
    answers, so a user who says "11:00, 30 minutes" gets exactly that rather
    than the whole stretch.
    """
    if not gaps:
        return None
    target = None
    for g in gaps:
        if g["start"] <= at <= g["end"]:
            target = g
            break
    if target is None:
        return None
    start = max(datetime.fromisoformat(target["start"]), datetime.fromisoformat(at))
    end = min(datetime.fromisoformat(target["end"]), start + timedelta(minutes=max(1, minutes)))
    return {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"), "note": note}