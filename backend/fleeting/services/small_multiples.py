"""#248 weekly small-multiples comparing all seven days."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from ..activity import app_blocked
from . import calendar_svc
from .metrics import daily_focus_score

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def get_weekly_small_multiples(
    db: Database,
    cfg: Config,
    *,
    week_start: str | None = None,
) -> dict:
    """Calculate 7 synchronized mini-day timelines for a Monday-to-Sunday week.

    Provides hourly screentime intensity (0-23h) for each day on an identical
    vertical scale to enable direct visual comparison of work patterns across the week.
    """
    today_dt = calendar_svc.today()
    if week_start:
        try:
            start_d = date.fromisoformat(week_start)
            # Align to Monday of that week
            start_d = start_d - timedelta(days=start_d.weekday())
        except ValueError:
            start_d = today_dt - timedelta(days=today_dt.weekday())
    else:
        start_d = today_dt - timedelta(days=today_dt.weekday())

    week_days = [(start_d + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    today_str = today_dt.strftime("%Y-%m-%d")

    days_data = []
    total_week_seconds = 0
    max_hourly_sec = 0

    for idx, d_str in enumerate(week_days):
        raw_sessions = db.activity_sessions(d_str)
        sessions = [
            s for s in raw_sessions
            if not app_blocked(cfg.activity, db, s["app_class"])
        ]

        hourly_secs = [0] * 24
        app_secs: dict[str, int] = defaultdict(int)
        project_secs: dict[str, int] = defaultdict(int)
        day_total = 0

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

            if dt.tzinfo is not None:
                z = calendar_svc.zone(calendar_svc.current_tz())
                dt = dt.astimezone(z) if z else dt.astimezone()

            start_sec = dt.hour * 3600 + dt.minute * 60 + dt.second
            end_sec = min(86400, start_sec + secs)
            actual_secs = end_sec - start_sec

            day_total += actual_secs
            app_name = s.get("app_class") or "Unknown"
            proj_name = s.get("project") or ""
            app_secs[app_name] += actual_secs
            if proj_name:
                project_secs[proj_name] += actual_secs

            # Distribute into hourly buckets
            cur_sec = start_sec
            while cur_sec < end_sec:
                h = cur_sec // 3600
                next_h = (h + 1) * 3600
                chunk = min(end_sec, next_h) - cur_sec
                if 0 <= h < 24:
                    hourly_secs[h] += chunk
                cur_sec = next_h

        for h_sec in hourly_secs:
            if h_sec > max_hourly_sec:
                max_hourly_sec = h_sec

        top_app = max(app_secs.items(), key=lambda kv: kv[1])[0] if app_secs else None
        top_project = max(project_secs.items(), key=lambda kv: kv[1])[0] if project_secs else None

        # Focus score for the day
        score_info = daily_focus_score(db, d_str)
        focus_score = score_info.get("score", 0)

        days_data.append({
            "day": d_str,
            "day_of_week": DAY_NAMES[idx],
            "day_index": idx,
            "is_today": d_str == today_str,
            "is_future": d_str > today_str,
            "total_seconds": day_total,
            "focus_score": focus_score,
            "top_app": top_app,
            "top_project": top_project,
            "hourly": hourly_secs,
        })

        total_week_seconds += day_total

    active_days_count = sum(1 for d in days_data if d["total_seconds"] > 0)
    avg_daily_seconds = round(total_week_seconds / max(1, active_days_count)) if active_days_count > 0 else 0

    return {
        "week_start": week_days[0],
        "week_end": week_days[6],
        "total_seconds": total_week_seconds,
        "avg_daily_seconds": avg_daily_seconds,
        "max_hourly_seconds": max(1800, max_hourly_sec),
        "days": days_data,
    }
