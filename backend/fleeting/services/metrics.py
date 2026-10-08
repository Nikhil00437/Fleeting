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


def daily_focus_score(db: Database, day: str) -> dict:
    """#57 compute a 0-100 focus score for a day.

    Components:
    - Duration (0-40 pts): active screentime towards 4 hours (14400s) benchmark
    - Stretch (0-35 pts): uninterrupted time per context switch (30m benchmark)
    - Project alignment (0-25 pts): fraction of time on identified projects
    """
    sessions = _sessions(db, day)
    total_seconds = sum(int(s["seconds"] or 0) for s in sessions)
    if total_seconds == 0:
        return {
            "day": day,
            "score": 0,
            "grade": "Rest / Inactive",
            "total_seconds": 0,
            "components": {
                "duration": 0.0,
                "stretch": 0.0,
                "project": 0.0,
            },
            "switches": 0,
            "seconds_per_switch": None,
            "project_seconds": 0,
        }

    # 1. Duration (0-40)
    dur_score = min(40.0, (total_seconds / 14400.0) * 40.0)

    # 2. Stretch / switches (0-35)
    sw_data = context_switches(db, day)
    switches = sw_data["switches"]
    sec_per_switch = sw_data["seconds_per_switch"] or total_seconds
    # 1800s (30m) average stretch = full 35 pts
    stretch_score = min(35.0, (sec_per_switch / 1800.0) * 35.0)

    # 3. Project alignment (0-25)
    proj_seconds = sum(int(s["seconds"] or 0) for s in sessions if s.get("project"))
    proj_score = (proj_seconds / total_seconds) * 25.0

    raw_score = dur_score + stretch_score + proj_score
    score = int(round(min(100.0, max(0.0, raw_score))))

    if score >= 80:
        grade = "Deep Focus"
    elif score >= 60:
        grade = "Productive"
    elif score >= 40:
        grade = "Moderate"
    elif score >= 1:
        grade = "Scattered"
    else:
        grade = "Rest / Inactive"

    return {
        "day": day,
        "score": score,
        "grade": grade,
        "total_seconds": total_seconds,
        "components": {
            "duration": round(dur_score, 1),
            "stretch": round(stretch_score, 1),
            "project": round(proj_score, 1),
        },
        "switches": switches,
        "seconds_per_switch": sec_per_switch,
        "project_seconds": proj_seconds,
    }


def focus_score_trend(db: Database, *, days: int = 14, end_day: str | None = None) -> dict:
    """#57 multi-day focus score trend, average and streak."""
    end_d = date.fromisoformat(end_day) if end_day else datetime.now().astimezone().date()
    start_d = end_d - timedelta(days=days - 1)

    rows = db.execute(
        "SELECT day FROM activity WHERE day >= ? AND day <= ? AND seconds >= 1 GROUP BY day",
        (start_d.isoformat(), end_d.isoformat()),
    ).fetchall()
    active_days_set = {r["day"] for r in rows}

    day_list = []
    curr = start_d
    while curr <= end_d:
        day_str = curr.isoformat()
        if day_str in active_days_set:
            day_list.append(daily_focus_score(db, day_str))
        else:
            day_list.append({
                "day": day_str,
                "score": 0,
                "grade": "Rest / Inactive",
                "total_seconds": 0,
                "components": {"duration": 0.0, "stretch": 0.0, "project": 0.0},
                "switches": 0,
                "seconds_per_switch": None,
                "project_seconds": 0,
            })
        curr += timedelta(days=1)

    active_scores = [d["score"] for d in day_list if d["score"] > 0]
    avg_score = round(sum(active_scores) / len(active_scores), 1) if active_scores else 0.0

    streak = 0
    for d in reversed(day_list):
        if d["score"] >= 50:
            streak += 1
        elif d["total_seconds"] > 0:
            break
        else:
            break

    if len(day_list) >= 6:
        recent = sum(d["score"] for d in day_list[-3:]) / 3.0
        prior = sum(d["score"] for d in day_list[-6:-3]) / 3.0
        if recent > prior + 5:
            direction = "improving"
        elif recent < prior - 5:
            direction = "declining"
        else:
            direction = "stable"
    else:
        direction = "stable"

    best_day = max(day_list, key=lambda d: d["score"], default=None)

    return {
        "days": day_list,
        "average_score": avg_score,
        "streak_days": streak,
        "direction": direction,
        "active_days_count": len(active_scores),
        "best_day": {"day": best_day["day"], "score": best_day["score"]} if best_day else None,
    }