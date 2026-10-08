"""#169 Persistent unfinished threads list from reports.

Aggregates open questions, loose ends, blockers, and stale carried-over tasks
from daily and weekly digests into a persistent tracker where they can be
converted to tasks, marked resolved, or dismissed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime
from typing import Any

from ..db import Database, _row_to_task

log = logging.getLogger("fleeting.unfinished_threads")

_SECTION_RE = re.compile(
    r"^##\s*(questions for tomorrow|blockers|loose ends|still open|open questions|unfinished threads)",
    re.IGNORECASE,
)


def _get_set_from_kv(db: Database, key: str) -> set[str]:
    raw = db.kv_get(key, "[]") or "[]"
    try:
        return set(json.loads(raw))
    except Exception:
        return set()


def _save_set_to_kv(db: Database, key: str, items: set[str]) -> None:
    db.kv_set(key, json.dumps(sorted(list(items))))


def _extract_markdown_threads(day: str, text: str) -> list[dict[str, Any]]:
    """Extract bullet points under questions/blockers/loose ends headers."""
    lines = text.splitlines()
    in_target_section = False
    threads: list[dict[str, Any]] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_target_section = bool(_SECTION_RE.match(stripped))
            continue
        elif stripped.startswith("#"):
            in_target_section = False
            continue

        if in_target_section and (stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s+", stripped)):
            # Clean bullet text
            item = re.sub(r"^(?:[-*]|\d+\.)\s+", "", stripped).strip()
            # Ignore placeholder lines like "None." or "None recorded."
            if item.lower().startswith("none") or item.lower().startswith("no "):
                continue
            if len(item) < 3:
                continue

            h = hashlib.sha1(f"{day}:{item}".encode("utf-8")).hexdigest()[:12]
            thread_id = f"thread_{h}"
            threads.append(
                {
                    "id": thread_id,
                    "text": item,
                    "source_day": day,
                    "source_type": "daily_log",
                    "created_at": f"{day}T00:00:00+00:00",
                }
            )

    return threads


def get_unfinished_threads(db: Database) -> list[dict[str, Any]]:
    """Gather all unresolved threads from daily logs and stale tasks."""
    resolved = _get_set_from_kv(db, "threads:resolved")
    dismissed = _get_set_from_kv(db, "threads:dismissed")
    excluded = resolved | dismissed

    today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    today_date = date.fromisoformat(today_str)

    threads: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    # 1. From stored daily logs (past 60 days)
    daily_rows = db.execute(
        "SELECT day, summary_md, edited_body FROM daily_logs ORDER BY day DESC LIMIT 60"
    ).fetchall()
    for row in daily_rows:
        day = row["day"]
        content = row["edited_body"] or row["summary_md"] or ""
        for t in _extract_markdown_threads(day, content):
            if t["id"] not in excluded and t["text"].lower() not in seen_texts:
                src_date = date.fromisoformat(t["source_day"])
                t["age_days"] = max(0, (today_date - src_date).days)
                threads.append(t)
                seen_texts.add(t["text"].lower())

    # 2. From stale carried-over tasks (open >= 2 days)
    task_rows = db.execute(
        "SELECT * FROM tasks WHERE done = 0 ORDER BY created_at ASC"
    ).fetchall()
    for row in task_rows:
        t_dict = _row_to_task(row)
        task_id = f"task_{t_dict['id']}"
        if task_id in excluded or t_dict["text"].lower() in seen_texts:
            continue

        created_day = (t_dict.get("created_at") or today_str)[:10]
        try:
            c_date = date.fromisoformat(created_day)
            age = (today_date - c_date).days
        except Exception:
            age = 0

        # Include if older than 1 day or has blockers
        if age >= 2 or t_dict.get("waiting_for") or t_dict.get("blocked_by"):
            threads.append(
                {
                    "id": task_id,
                    "text": t_dict["text"],
                    "source_day": created_day,
                    "source_type": "task",
                    "task_id": t_dict["id"],
                    "created_at": t_dict["created_at"],
                    "age_days": age,
                    "waiting_for": t_dict.get("waiting_for"),
                    "blocked_by": t_dict.get("blocked_by"),
                }
            )
            seen_texts.add(t_dict["text"].lower())

    # Sort: highest age first
    threads.sort(key=lambda x: (x["age_days"], x["source_day"]), reverse=True)
    return threads


def resolve_thread(db: Database, thread_id: str, action: str = "resolve") -> None:
    """Mark thread as resolved or dismissed persistently."""
    key = "threads:resolved" if action == "resolve" else "threads:dismissed"
    items = _get_set_from_kv(db, key)
    items.add(thread_id)
    _save_set_to_kv(db, key, items)


def convert_thread_to_task(db: Database, thread_id: str, text: str) -> dict[str, Any]:
    """Convert an unfinished thread into a real task, marking the thread resolved."""
    task = db.insert_task(
        {
            "text": text,
            "done": False,
            "priority": "P2",
            "list": "inbox",
        }
    )
    resolve_thread(db, thread_id, "resolve")
    return task
