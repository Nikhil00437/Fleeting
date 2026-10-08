"""#342 activity export: a CSV of sessions, and a timesheet by project.

Both are pure renderers — the router decides how they are delivered — so the
same text can be downloaded, mailed to a timesheet, or written into the vault.

CSV is written by hand rather than via `csv` because the values are ours
(window titles can contain commas, quotes and newlines) and the quoting rule
is three lines. `csv.writer` would do the same job with an import.
"""

from __future__ import annotations

import io
from typing import Any

from ..db import Database

SESSION_COLUMNS = (
    "date",
    "start",
    "end",
    "minutes",
    "app",
    "project",
    "branch",
    "workspace",
    "title",
    "note",
)

TIMESHEET_COLUMNS = ("date", "project", "minutes", "sessions", "apps")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if any(ch in text for ch in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def render_csv(rows: list[list[Any]], columns: tuple[str, ...]) -> str:
    out = io.StringIO()
    out.write(",".join(_cell(c) for c in columns) + "\n")
    for row in rows:
        out.write(",".join(_cell(v) for v in row) + "\n")
    return out.getvalue()


def sessions_in_range(db: Database, day_from: str | None = None, day_to: str | None = None) -> list[dict]:
    where, params = ["seconds >= 1"], []
    if day_from:
        where.append("day >= ?")
        params.append(day_from)
    if day_to:
        where.append("day <= ?")
        params.append(day_to)
    rows = db.execute(
        "SELECT * FROM activity WHERE "
        + " AND ".join(where)
        + " ORDER BY day, first_seen LIMIT 20000",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def render_sessions_csv(sessions: list[dict]) -> str:
    """One row per session, in the order the day happened."""
    rows = [
        [
            s.get("day"),
            (s.get("first_seen") or "")[11:19],
            (s.get("last_seen") or "")[11:19],
            round((s.get("seconds") or 0) / 60),
            s.get("app_class"),
            s.get("project"),
            s.get("branch"),
            s.get("workspace"),
            s.get("title"),
            s.get("note"),
        ]
        for s in sessions
    ]
    return render_csv(rows, SESSION_COLUMNS)


def render_timesheet_csv(sessions: list[dict]) -> str:
    """Day × project totals, with a `day,all` row per day for the hours total.

    The `all` row is what a timesheet wants: what did you bill that day.
    """
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for s in sessions:
        key = (s.get("day") or "", s.get("project") or "unassigned")
        b = buckets.setdefault(key, {"seconds": 0, "sessions": 0, "apps": set()})
        b["seconds"] += int(s.get("seconds") or 0)
        b["sessions"] += 1
        b["apps"].add(s.get("app_class") or "")

    rows: list[list[Any]] = []
    days: dict[str, int] = {}
    for (day, project), b in sorted(buckets.items()):
        rows.append([day, project, round(b["seconds"] / 60), b["sessions"], ", ".join(sorted(b["apps"]))])
        days[day] = days.get(day, 0) + b["seconds"]
    for day, seconds in sorted(days.items()):
        rows.append([day, "all", round(seconds / 60), "", ""])
    return render_csv(rows, TIMESHEET_COLUMNS)