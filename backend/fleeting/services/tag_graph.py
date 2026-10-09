"""#249 tag co-occurrence matrix and topic-over-time stream chart."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, TYPE_CHECKING

from . import calendar_svc

if TYPE_CHECKING:
    from ..db import Database


def _parse_tags(raw: Any) -> list[str]:
    """Parse tag array or JSON/comma string into normalized lowercase unique tags."""
    if not raw:
        return []
    if isinstance(raw, list):
        return sorted({str(t).strip().lower() for t in raw if str(t).strip()})
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return sorted({str(t).strip().lower() for t in parsed if str(t).strip()})
            except Exception:
                pass
        return sorted({t.strip().lower() for t in text.split(",") if t.strip()})
    return []


def get_tag_cooccurrence_and_stream(
    db: Database,
    *,
    top_n: int = 8,
    weeks: int = 8,
) -> dict:
    """Calculate tag co-occurrence matrix and topic-over-time stream data.

    1. Matrix: NxN frequency of tags co-occurring on the same notes.
    2. Stream: weekly distribution of notes for each top tag over `weeks` weeks.
    """
    top_n = max(2, min(top_n, 20))
    weeks = max(2, min(weeks, 26))

    rows = db.execute(
        """
        SELECT id, tags, created_at
        FROM notes
        WHERE trashed_at IS NULL AND tags IS NOT NULL AND length(trim(tags)) > 0
        """
    ).fetchall()

    tag_freq: dict[str, int] = defaultdict(int)
    note_tags_list: list[tuple[list[str], str]] = []

    for r in rows:
        tags = _parse_tags(r["tags"])
        if not tags:
            continue
        c_day = calendar_svc.date_tag(r["created_at"]) or ""
        note_tags_list.append((tags, c_day))
        for t in tags:
            tag_freq[t] += 1

    sorted_tags = sorted(tag_freq.items(), key=lambda kv: (-kv[1], kv[0]))
    top_tags = [t for t, _ in sorted_tags[:top_n]]
    n = len(top_tags)
    tag_index = {t: idx for idx, t in enumerate(top_tags)}

    # Build NxN Co-occurrence Matrix
    matrix = [[0] * n for _ in range(n)]
    pairs = []

    for tags, _ in note_tags_list:
        present_indices = [tag_index[t] for t in tags if t in tag_index]
        for i in present_indices:
            matrix[i][i] += 1
        for i_idx, i in enumerate(present_indices):
            for j in present_indices[i_idx + 1:]:
                matrix[i][j] += 1
                matrix[j][i] += 1

    for i in range(n):
        for j in range(i + 1, n):
            if matrix[i][j] > 0:
                pairs.append({
                    "tag_a": top_tags[i],
                    "tag_b": top_tags[j],
                    "count": matrix[i][j],
                })

    pairs.sort(key=lambda p: -p["count"])

    # Build Topic-Over-Time Stream Buckets
    today_dt = calendar_svc.today()
    cur_monday = today_dt - timedelta(days=today_dt.weekday())
    start_monday = cur_monday - timedelta(weeks=weeks - 1)

    week_starts = [start_monday + timedelta(weeks=w) for w in range(weeks)]
    week_labels = [ws.strftime("%Y-%m-%d") for ws in week_starts]

    tag_week_counts: dict[str, list[int]] = {t: [0] * weeks for t in top_tags}

    for tags, c_day in note_tags_list:
        if not c_day:
            continue
        try:
            note_date = date.fromisoformat(c_day)
        except ValueError:
            continue

        if note_date < start_monday:
            continue

        # Find which week bucket it falls into
        days_from_start = (note_date - start_monday).days
        if days_from_start < 0:
            continue
        w_idx = days_from_start // 7
        if 0 <= w_idx < weeks:
            for t in tags:
                if t in tag_week_counts:
                    tag_week_counts[t][w_idx] += 1

    stream_series = [
        {
            "tag": t,
            "total_in_window": sum(tag_week_counts[t]),
            "counts": tag_week_counts[t],
        }
        for t in top_tags
    ]

    return {
        "top_tags": [{"tag": t, "count": tag_freq[t]} for t in top_tags],
        "matrix": matrix,
        "pairs": pairs,
        "weeks": week_labels,
        "stream": stream_series,
        "total_tagged_notes": len(note_tags_list),
    }
