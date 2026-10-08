"""#63 "what was I doing here?" — ask about a stretch of the timeline.

The context is built from the sessions inside the range, not from a search of
the whole corpus, so the answer is grounded in that window. With no LLM the
extractive fallback still answers usefully: it reports the apps, the projects
and whatever the user annotated (#334) inside the range.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..config import Config
from ..db import Database
from .dailylog import build_transcript

log = logging.getLogger("fleeting.activity_ask")


def sessions_in_window(db: Database, day: str, start: str, end: str) -> list[dict]:
    rows = db.execute(
        "SELECT * FROM activity WHERE day = ? AND seconds >= 1 AND first_seen < ?"
        " AND last_seen > ? ORDER BY first_seen",
        (day, end, start),
    ).fetchall()
    return [dict(r) for r in rows]


def describe_window(sessions: list[dict]) -> str:
    """The no-LLM answer: what ran, for how long, and what it was for."""
    if not sessions:
        return "Nothing was tracked in that stretch."
    total = sum(int(s.get("seconds") or 0) for s in sessions)
    apps: dict[str, int] = {}
    for s in sessions:
        apps[s["app_class"]] = apps.get(s["app_class"], 0) + int(s.get("seconds") or 0)

    lines = [f"{len(sessions)} sessions, {_hm(total)} tracked."]
    for app, secs in sorted(apps.items(), key=lambda kv: -kv[1])[:6]:
        lines.append(f"- {app}: {_hm(secs)}")
    projects = {s.get("project") for s in sessions if s.get("project")}
    if projects:
        lines.append(f"- projects: {', '.join(sorted(projects))}")
    notes = [s["note"] for s in sessions if (s.get("note") or "").strip()]
    if notes:
        lines.append("- you noted: " + "; ".join(notes[:4]))
    return "\n".join(lines)


def _hm(seconds: int) -> str:
    hours, mins = divmod(int(seconds) // 60, 60)
    if not hours:
        return f"{mins}m"
    return f"{hours}h{mins:02d}m" if mins else f"{hours}h"


def validate_window(day: str, start: str, end: str) -> tuple[str, str]:
    """Both bounds must be inside the day and in order, or the query is
    nonsense — and a reversed range would silently return everything."""
    try:
        day_start = datetime.fromisoformat(f"{day}T00:00:00")
        day_end = datetime.fromisoformat(f"{day}T23:59:59")
        a = datetime.fromisoformat(start)
        b = datetime.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("start and end must be ISO timestamps on that day") from exc
    if not (day_start <= a < b <= day_end):
        raise ValueError("the range must sit inside the day and start before it ends")
    return a.replace(microsecond=0).isoformat(), b.replace(microsecond=0).isoformat()


async def answer_window(
    db: Database, cfg: Config, day: str, start: str, end: str, question: str = ""
) -> dict:
    """The window's sessions plus an answer about them."""
    win_start, win_end = validate_window(day, start, end)
    sessions = sessions_in_window(db, day, win_start, win_end)
    question = (question or "What was I doing here?").strip()
    summary = describe_window(sessions)

    answer = summary
    used_llm = False
    if sessions and cfg.llm.provider != "none":
        answer = await _ask_llm(cfg, question, summary, sessions, db)
        used_llm = answer != summary

    return {
        "day": day,
        "start": win_start,
        "end": win_end,
        "question": question,
        "answer": answer or summary,
        "sessions": [
            {
                "id": s["id"],
                "app_class": s["app_class"],
                "title": s["title"],
                "first_seen": s["first_seen"],
                "last_seen": s["last_seen"],
                "seconds": s["seconds"],
                "project": s.get("project"),
                "note": s.get("note"),
            }
            for s in sessions
        ],
        "used_llm": used_llm,
    }


async def _ask_llm(
    cfg: Config, question: str, summary: str, sessions: list[dict], db: Database
) -> str:
    from .llm import LLMUnavailable, auth_headers, normalize_base_url, request_chat

    prompt = (
        "A user is looking at one stretch of their tracked day and asks:\n"
        f'"{question}"\n\nRaw record of that stretch:\n{summary}\n\n'
        "Answer from this record only. If it does not say, say so."
    )
    try:
        resp = await request_chat(
            normalize_base_url(cfg.llm.base_url),
            cfg.llm.model,
            [{"role": "user", "content": prompt}],
            timeout=cfg.llm.timeout_secs,
            provider=cfg.llm.provider,
            headers=auth_headers(cfg.llm),
        )
    except (LLMUnavailable, Exception) as exc:  # noqa: B014 - any failure falls back
        log.info("window question fell back to the extractive answer: %s", exc)
        return summary
    return str(resp).strip() or summary