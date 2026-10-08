"""Activity metrics: context switches, today vs average, and a calendar grid.

All three read the same `activity` rows, so they share one query each and one
definition of "switch" — otherwise the numbers on two cards would disagree.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..db import Database

# A change of window class, a jump of more than this many minutes, or a change
# of project. Anything smaller is reading, not switching contexts.
SWITCH_GAP_SECS = 180


def _sessions(db: Database, day: str) -> list[dict]:
    rows = db.execute(
        "SELECT app_class, project, first_seen, last_seen, seconds FROM activity"
        " WHERE day = ? AND seconds >= 1 ORDER BY first_seen",
        (day,),
    ).fetchall()
    return [dict(r) for r in rows]


def context_switches(db: Database, day: str, *, gap_secs: int = SWITCH_GAP_SECS) -> dict:
    """#58 how many times the day changed what it was doing."""
    sessions = _sessions(db, day)
    switches = 0
    reasons = {"app": 0, "gap": 0, "project": 0}
    for prev, cur in zip(sessions, sessions[1:]):
        try:
            gap = (
                datetime.fromisoformat(cur["first_seen"]) - datetime.fromisoformat(prev["last_seen"])
            ).total_seconds()
        except ValueError:
            continue
        if prev["app_class"] != cur["app_class"]:
            switches += 1
            reasons["app"] += 1
        elif (prev.get("project") or None) != (cur.get("project") or None):
            switches += 1
            reasons["project"] += 1
        elif gap > gap_secs:
            switches += 1
            reasons["gap"] += 1

    total = sum(int(s["seconds"] or 0) for s in sessions)
    return {
        "day": day,
        "switches": switches,
        "reasons": reasons,
        "sessions": len(sessions),
        "seconds_per_switch": round(total / switches) if switches else None,
    }


def today_vs_average(db: Database, day: str, *, window: int = 7) -> dict:
    """#62 today's tracked seconds against the mean of the previous `window` days.

    The average deliberately excludes today: comparing a day with itself would
    halve the difference and make every day look closer to normal than it is.
    """
    total = sum(int(s["seconds"] or 0) for s in _sessions(db, day))
    start = datetime.fromisoformat(day).date() - timedelta(days=window)
    rows = db.execute(
        "SELECT day, SUM(seconds) AS seconds FROM activity"
        " WHERE day >= ? AND day < ? AND seconds >= 1 GROUP BY day",
        (start.isoformat(), day),
    ).fetchall()
    per_day = {r["day"]: r["seconds"] or 0 for r in rows}
    average = sum(per_day.values()) / window if window else 0.0
    delta = total - average
    return {
        "day": day,
        "seconds": total,
        "average_seconds": round(average),
        "delta_seconds": round(delta),
        "pct": round(delta / average * 100) if average else None,
        "window": window,
        "days_tracked": len(per_day),
    }


def heatmap(db: Database, *, weeks: int = 12, end: str | None = None) -> dict:
    """#59 a calendar grid of active minutes, one cell per day.

    Cells are `YYYY-MM-DD` keys with a minute count; the UI decides the colour
    ramp, so there is exactly one place to change how "busy" looks.
    """
    end_day = date.fromisoformat(end) if end else datetime.now().astimezone().date()
    start_day = end_day - timedelta(days=weeks * 7 - 1)
    rows = db.execute(
        "SELECT day, SUM(seconds) AS seconds FROM activity"
        " WHERE day >= ? AND day <= ? AND seconds >= 1 GROUP BY day",
        (start_day.isoformat(), end_day.isoformat()),
    ).fetchall()
    return {
        "from": start_day.isoformat(),
        "to": end_day.isoformat(),
        "weeks": weeks,
        "cells": [{"day": r["day"], "minutes": round((r["seconds"] or 0) / 60)} for r in rows],
        "peak_minutes": max([round((r["seconds"] or 0) / 60) for r in rows], default=0),
    }