"""#251 project time treemap service."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING

from ..activity import app_blocked
from . import calendar_svc

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database


def get_project_treemap(
    db: Database,
    cfg: Config,
    *,
    days: int = 7,
    day: str | None = None,
) -> dict:
    """Calculate hierarchical time breakdown (Project -> Application) for a treemap.

    Groups telemetry by project and application, providing nested time totals
    and percentages over the requested window.
    """
    days = max(1, min(days, 365))
    params: list = []

    if day:
        where_clause = "WHERE day = ?"
        params.append(day)
    else:
        today_dt = calendar_svc.today()
        start_day = (today_dt - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        where_clause = "WHERE day >= ?"
        params.append(start_day)

    rows = db.execute(
        f"""
        SELECT project, app_class, seconds
        FROM activity
        {where_clause} AND seconds >= 1
        """,
        params,
    ).fetchall()

    project_app_secs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    project_display_names: dict[str, str] = {}
    total_seconds = 0

    for r in rows:
        app = r["app_class"] or "Unknown"
        if app_blocked(cfg.activity, db, app):
            continue

        secs = int(r["seconds"] or 0)
        if secs <= 0:
            continue

        raw_proj = (r["project"] or "").strip()
        proj_key = raw_proj.lower() if raw_proj else "general"
        if proj_key not in project_display_names:
            project_display_names[proj_key] = raw_proj if raw_proj else "General"

        project_app_secs[proj_key][app] += secs
        total_seconds += secs

    projects_list = []

    for proj_key, apps_map in project_app_secs.items():
        proj_secs = sum(apps_map.values())
        if proj_secs <= 0:
            continue

        proj_name = project_display_names.get(proj_key, proj_key)
        proj_pct = round((proj_secs / total_seconds) * 100.0, 1) if total_seconds > 0 else 0.0

        apps_list = []
        for app_name, a_secs in sorted(apps_map.items(), key=lambda kv: -kv[1]):
            apps_list.append({
                "name": app_name,
                "seconds": a_secs,
                "pct_of_project": round((a_secs / proj_secs) * 100.0, 1),
                "pct_of_total": round((a_secs / total_seconds) * 100.0, 1) if total_seconds > 0 else 0.0,
            })

        projects_list.append({
            "name": proj_name,
            "seconds": proj_secs,
            "pct": proj_pct,
            "apps": apps_list,
        })

    projects_list.sort(key=lambda p: -p["seconds"])

    return {
        "window_days": days,
        "day": day,
        "total_seconds": total_seconds,
        "project_count": len(projects_list),
        "projects": projects_list,
    }
