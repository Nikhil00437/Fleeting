"""#247 24-hour radial day clock service."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..activity import app_blocked
from . import calendar_svc

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database


def get_radial_clock(db: Database, cfg: Config, day: str) -> dict:
    """Compute 24-hour radial clock visualization data for a single day.

    Translates sessions into angular polar arc segments (0° = 00:00, 90° = 06:00,
    180° = 12:00, 270° = 18:00, 360° = 24:00) alongside 24 hourly buckets.
    """
    raw_sessions = db.activity_sessions(day)
    sessions = [
        s for s in raw_sessions
        if not app_blocked(cfg.activity, db, s["app_class"])
    ]

    segments = []
    hourly_secs: list[int] = [0] * 24
    hourly_apps: list[dict[str, int]] = [defaultdict(int) for _ in range(24)]
    hourly_projects: list[dict[str, int]] = [defaultdict(int) for _ in range(24)]

    app_totals: dict[str, int] = defaultdict(int)
    project_totals: dict[str, int] = defaultdict(int)

    total_seconds = 0
    daytime_seconds = 0
    night_seconds = 0

    for s in sessions:
        secs = int(s.get("seconds") or 0)
        if secs <= 0:
            continue

        first_iso = s.get("first_seen")
        if not first_iso:
            continue

        try:
            dt = datetime.fromisoformat(first_iso)
        except ValueError:
            continue

        # Convert to local time if timezone aware
        if dt.tzinfo is not None:
            z = calendar_svc.zone(calendar_svc.current_tz())
            dt = dt.astimezone(z) if z else dt.astimezone()

        start_sec_of_day = dt.hour * 3600 + dt.minute * 60 + dt.second
        end_sec_of_day = min(86400, start_sec_of_day + secs)
        actual_secs = end_sec_of_day - start_sec_of_day

        start_deg = round((start_sec_of_day / 86400.0) * 360.0, 2)
        end_deg = round((end_sec_of_day / 86400.0) * 360.0, 2)

        app_name = s.get("app_class") or "Unknown"
        proj_name = s.get("project") or "General"
        title = s.get("title") or ""

        segments.append({
            "id": s.get("id"),
            "app_class": app_name,
            "project": proj_name,
            "title": title,
            "seconds": actual_secs,
            "start_time": dt.strftime("%H:%M"),
            "end_time": f"{(end_sec_of_day // 3600):02d}:{(end_sec_of_day % 3600 // 60):02d}",
            "start_deg": start_deg,
            "end_deg": max(start_deg + 0.5, end_deg),
        })

        total_seconds += actual_secs
        app_totals[app_name] += actual_secs
        project_totals[proj_name] += actual_secs

        # Populate hourly buckets (distribute session seconds across hour boundaries)
        cur_sec = start_sec_of_day
        while cur_sec < end_sec_of_day:
            h = cur_sec // 3600
            next_h_sec = (h + 1) * 3600
            chunk = min(end_sec_of_day, next_h_sec) - cur_sec
            if 0 <= h < 24:
                hourly_secs[h] += chunk
                hourly_apps[h][app_name] += chunk
                hourly_projects[h][proj_name] += chunk
                if 6 <= h < 18:
                    daytime_seconds += chunk
                else:
                    night_seconds += chunk
            cur_sec = next_h_sec

    hourly_list = []
    peak_hour = 0
    max_h_sec = 0

    for h in range(24):
        s_count = hourly_secs[h]
        if s_count > max_h_sec:
            max_h_sec = s_count
            peak_hour = h

        top_app = max(hourly_apps[h].items(), key=lambda kv: kv[1])[0] if hourly_apps[h] else None
        top_proj = max(hourly_projects[h].items(), key=lambda kv: kv[1])[0] if hourly_projects[h] else None

        hourly_list.append({
            "hour": h,
            "seconds": s_count,
            "top_app": top_app,
            "top_project": top_proj,
        })

    apps_list = [
        {
            "app": app,
            "seconds": s_cnt,
            "pct": round((s_cnt / total_seconds) * 100, 1) if total_seconds > 0 else 0.0,
        }
        for app, s_cnt in sorted(app_totals.items(), key=lambda kv: -kv[1])
    ]

    projects_list = [
        {
            "project": proj,
            "seconds": s_cnt,
            "pct": round((s_cnt / total_seconds) * 100, 1) if total_seconds > 0 else 0.0,
        }
        for proj, s_cnt in sorted(project_totals.items(), key=lambda kv: -kv[1])
    ]

    return {
        "day": day,
        "total_seconds": total_seconds,
        "daytime_seconds": daytime_seconds,
        "night_seconds": night_seconds,
        "peak_hour": peak_hour,
        "segments": segments,
        "hourly": hourly_list,
        "apps": apps_list,
        "projects": projects_list,
    }
