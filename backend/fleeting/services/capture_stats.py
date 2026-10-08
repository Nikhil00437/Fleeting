"""#163 Capture frequency stats: notes per day, top tags over time.

Analyzes capture habits over 7, 14, 30, or 90 days:
- Daily capture volume split by note type (text, voice, youtube)
- Summary KPIs (total captures, daily average, busiest day, peak capture hour)
- Hour-of-day and Day-of-week heat patterns
- Top tags over time with timeline distribution (#163, #168)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..db import Database, datetime_now_local


def get_capture_frequency_stats(db: Database, days: int = 30) -> dict[str, Any]:
    days = min(max(days, 2), 90)
    offset_param = f"-{days} days"
    now_local = datetime_now_local()

    # 1. Daily capture breakdown
    rows = db.execute(
        """
        SELECT
          date(created_at, 'localtime') AS d,
          COUNT(*) AS total_count,
          SUM(CASE WHEN type = 'text' THEN 1 ELSE 0 END) AS text_count,
          SUM(CASE WHEN type = 'voice' THEN 1 ELSE 0 END) AS voice_count,
          SUM(CASE WHEN type = 'youtube' THEN 1 ELSE 0 END) AS youtube_count
        FROM notes
        WHERE trashed_at IS NULL AND created_at >= datetime('now', :offset)
        GROUP BY d
        ORDER BY d ASC
        """,
        {"offset": offset_param},
    ).fetchall()

    by_day_map = {
        r["d"]: {
            "count": int(r["total_count"] or 0),
            "text": int(r["text_count"] or 0),
            "voice": int(r["voice_count"] or 0),
            "youtube": int(r["youtube_count"] or 0),
        }
        for r in rows
    }

    # Fill every day in the window
    notes_per_day: list[dict[str, Any]] = []
    total_captures = 0
    busiest_day: dict[str, Any] | None = None

    for i in range(days - 1, -1, -1):
        d_str = (now_local - timedelta(days=i)).strftime("%Y-%m-%d")
        counts = by_day_map.get(d_str, {"count": 0, "text": 0, "voice": 0, "youtube": 0})
        total_captures += counts["count"]
        point = {
            "day": d_str,
            "count": counts["count"],
            "text": counts["text"],
            "voice": counts["voice"],
            "youtube": counts["youtube"],
        }
        notes_per_day.append(point)
        if busiest_day is None or counts["count"] > busiest_day["count"]:
            busiest_day = {"day": d_str, "count": counts["count"]}

    avg_per_day = round(total_captures / days, 2) if days > 0 else 0.0

    # 2. Time-of-day and Day-of-week distribution
    dow_rows = db.execute(
        """
        SELECT strftime('%w', created_at, 'localtime') AS dow, COUNT(*) AS count
        FROM notes
        WHERE trashed_at IS NULL AND created_at >= datetime('now', :offset)
        GROUP BY dow
        """,
        {"offset": offset_param},
    ).fetchall()
    # strftime %w: 0 = Sunday, 1 = Monday, ..., 6 = Saturday
    dow_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    dow_map = {int(r["dow"]): int(r["count"]) for r in dow_rows if r["dow"] is not None}
    by_dow = [{"name": dow_names[i], "index": i, "count": dow_map.get(i, 0)} for i in range(7)]

    hour_rows = db.execute(
        """
        SELECT CAST(strftime('%H', created_at, 'localtime') AS INTEGER) AS hr, COUNT(*) AS count
        FROM notes
        WHERE trashed_at IS NULL AND created_at >= datetime('now', :offset)
        GROUP BY hr
        ORDER BY hr ASC
        """,
        {"offset": offset_param},
    ).fetchall()
    hour_map = {int(r["hr"]): int(r["count"]) for r in hour_rows if r["hr"] is not None}
    by_hour = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    peak_hour_entry = max(by_hour, key=lambda x: x["count"]) if by_hour else {"hour": 0, "count": 0}
    peak_hour = peak_hour_entry["hour"] if peak_hour_entry["count"] > 0 else None

    # 3. Top tags over time
    top_tag_rows = db.execute(
        """
        SELECT je.value AS tag, COUNT(*) AS count
        FROM notes, json_each(notes.tags) je
        WHERE notes.trashed_at IS NULL AND notes.created_at >= datetime('now', :offset)
        GROUP BY je.value
        ORDER BY count DESC
        LIMIT 6
        """,
        {"offset": offset_param},
    ).fetchall()

    top_tag_names = [r["tag"] for r in top_tag_rows if r["tag"]]
    top_tags_over_time: list[dict[str, Any]] = []

    if top_tag_names:
        placeholders = ",".join("?" for _ in top_tag_names)
        tag_timeline_rows = db.execute(
            f"""
            SELECT
              je.value AS tag,
              date(notes.created_at, 'localtime') AS d,
              COUNT(*) AS count
            FROM notes, json_each(notes.tags) je
            WHERE notes.trashed_at IS NULL
              AND notes.created_at >= datetime('now', ?)
              AND je.value IN ({placeholders})
            GROUP BY tag, d
            ORDER BY d ASC
            """,
            (offset_param, *top_tag_names),
        ).fetchall()

        tag_day_map: dict[str, dict[str, int]] = {t: {} for t in top_tag_names}
        for r in tag_timeline_rows:
            tag_day_map[r["tag"]][r["d"]] = int(r["count"] or 0)

        for r in top_tag_rows:
            t = r["tag"]
            timeline = [
                {"day": pt["day"], "count": tag_day_map[t].get(pt["day"], 0)}
                for pt in notes_per_day
            ]
            top_tags_over_time.append(
                {
                    "tag": t,
                    "total": int(r["count"]),
                    "timeline": timeline,
                }
            )

    return {
        "days": days,
        "total_captures": total_captures,
        "avg_per_day": avg_per_day,
        "busiest_day": busiest_day if busiest_day and busiest_day["count"] > 0 else None,
        "peak_hour": peak_hour,
        "notes_per_day": notes_per_day,
        "by_dow": by_dow,
        "by_hour": by_hour,
        "top_tags_over_time": top_tags_over_time,
    }
