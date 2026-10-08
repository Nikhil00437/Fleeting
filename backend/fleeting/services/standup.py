"""#69 Standup generator: yesterday, today, blockers.

Generates an agile-style daily standup summarizing:
1. Yesterday (completed tasks, active sessions, commits, daily log notes)
2. Today (open / due tasks, priority items, planned work)
3. Blockers (tasks waiting on someone, blocked dependencies, open questions)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from ..config import Config, expand_path
from ..db import Database, _row_to_task
from .calendar_svc import date_tag
from .dailylog import fmt_secs, generate_with_llm
from .files_activity import collect_git_subjects
from .whatnow import _blocked_ids

log = logging.getLogger("fleeting.standup")


def _previous_workday(target_day: str, db: Database) -> str:
    """Determine the previous relevant day (e.g. yesterday, or Friday on Mondays)."""
    target_d = date.fromisoformat(target_day)
    candidate = target_d - timedelta(days=1)
    cand_str = candidate.isoformat()

    # If Monday (weekday 0), check if Sunday was idle and Friday had work
    if target_d.weekday() == 0:
        sunday_sessions = db.activity_sessions(cand_str)
        if not sunday_sessions:
            friday = (target_d - timedelta(days=3)).isoformat()
            if db.activity_sessions(friday):
                return friday

    return cand_str


def collect_standup_data(
    db: Database,
    cfg: Config,
    day: str | None = None,
) -> dict[str, Any]:
    """Gather all raw material for a daily standup."""
    target_day = day or date_tag()
    prev_day = _previous_workday(target_day, db)

    # 1. Yesterday's completed tasks
    completed_rows = db.execute(
        "SELECT * FROM tasks WHERE done = 1 AND completed_at LIKE ? ORDER BY completed_at DESC",
        (f"{prev_day}%",),
    ).fetchall()
    yesterday_tasks = [_row_to_task(r) for r in completed_rows]

    # 2. Yesterday's sessions and focus time
    yesterday_sessions = db.activity_sessions(prev_day)
    yesterday_seconds = sum(int(s.get("seconds") or 0) for s in yesterday_sessions)
    app_totals: dict[str, int] = {}
    for s in yesterday_sessions:
        app = s.get("app_class", "unknown")
        app_totals[app] = app_totals.get(app, 0) + int(s.get("seconds") or 0)
    yesterday_apps = [
        {"app_class": a, "seconds": s} for a, s in sorted(app_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    # 3. Yesterday's git commits
    yesterday_commits: list[dict[str, Any]] = []
    if cfg.activity.watch_dirs:
        try:
            dirs = [expand_path(p.strip()) for p in cfg.activity.watch_dirs.split(",") if p.strip()]
            start = datetime.fromisoformat(f"{prev_day}T00:00:00").astimezone()
            yesterday_commits = collect_git_subjects(dirs, since=start, until=start + timedelta(days=1))
        except Exception:
            log.warning("standup: commit collection failed", exc_info=True)

    yesterday_daily_log = db.get_daily_log(prev_day)

    # 4. Open tasks for today
    all_open_rows = db.execute("SELECT * FROM tasks WHERE done = 0").fetchall()
    all_open = [_row_to_task(r) for r in all_open_rows]

    # Blocked task IDs
    blocked_set = _blocked_ids(all_open)

    # Today tasks: due today or overdue, or P1/P2, and not blocked
    today_tasks = []
    blockers = []

    for t in all_open:
        is_blocked = (
            t["id"] in blocked_set
            or bool(t.get("waiting_for"))
            or "#blocked" in t.get("text", "").lower()
            or "[blocked]" in t.get("text", "").lower()
        )
        if is_blocked:
            blockers.append(t)
        else:
            # Filter for tasks relevant today: due today/overdue or high priority
            is_due = bool(t.get("due_date") and t["due_date"] <= target_day)
            is_high_pri = t.get("priority") in ("P1", "P2")
            if is_due or is_high_pri:
                today_tasks.append(t)

    # Sort today tasks: overdue first, then P1 > P2 > P3
    def _task_sort_key(t: dict[str, Any]) -> tuple[int, int, str]:
        due_rank = 0 if (t.get("due_date") and t["due_date"] < target_day) else (1 if t.get("due_date") == target_day else 2)
        pri_map = {"P1": 1, "P2": 2, "P3": 3}
        pri_rank = pri_map.get(t.get("priority") or "P3", 4)
        return (due_rank, pri_rank, t.get("text", ""))

    today_tasks.sort(key=_task_sort_key)

    # If fewer than 3 today tasks, pick other open inbox tasks
    if len(today_tasks) < 5:
        existing_ids = {t["id"] for t in today_tasks} | {t["id"] for t in blockers}
        for t in all_open:
            if t["id"] not in existing_ids and t.get("list") == "inbox":
                today_tasks.append(t)
                if len(today_tasks) >= 5:
                    break

    return {
        "day": target_day,
        "previous_day": prev_day,
        "yesterday_tasks": yesterday_tasks,
        "yesterday_seconds": yesterday_seconds,
        "yesterday_apps": yesterday_apps,
        "yesterday_commits": yesterday_commits,
        "yesterday_daily_log": yesterday_daily_log,
        "today_tasks": today_tasks,
        "blockers": blockers,
    }


def fallback_standup(data: dict[str, Any]) -> str:
    """Deterministic, high-quality Markdown standup when offline."""
    lines = [
        f"# Standup — {data['day']}",
        "",
        f"## Yesterday ({data['previous_day']})",
    ]

    # Accomplishments & focus
    yesterday_items: list[str] = []
    if data["yesterday_tasks"]:
        for t in data["yesterday_tasks"][:8]:
            yesterday_items.append(f"- Completed: **{t['text']}**")

    if data["yesterday_commits"]:
        for c in data["yesterday_commits"][:5]:
            repo = f"[{c.get('repo')}] " if c.get("repo") else ""
            yesterday_items.append(f"- Commit: {repo}{c.get('subject', '')}")

    if data["yesterday_seconds"] > 0:
        top_apps = ", ".join(
            f"{a['app_class']} ({fmt_secs(a['seconds'])})" for a in data["yesterday_apps"][:3]
        )
        yesterday_items.append(f"- Focused for **{fmt_secs(data['yesterday_seconds'])}** across {top_apps}.")
    elif not yesterday_items:
        yesterday_items.append("- No tracked activity or tasks completed.")

    lines.extend(yesterday_items)

    # Today
    lines.extend(["", "## Today"])
    if data["today_tasks"]:
        for t in data["today_tasks"][:8]:
            due_badge = f" *(due {t['due_date']})*" if t.get("due_date") else ""
            pri_badge = f" `[{t['priority']}]`" if t.get("priority") else ""
            lines.append(f"- {pri_badge} **{t['text']}**{due_badge}")
    else:
        lines.append("- Continue in-flight priorities and capture incoming work.")

    # Blockers
    lines.extend(["", "## Blockers"])
    if data["blockers"]:
        for b in data["blockers"][:6]:
            wait = f" (waiting for: {b['waiting_for']})" if b.get("waiting_for") else ""
            dep = f" (blocked by: {b['blocked_by']})" if b.get("blocked_by") else ""
            lines.append(f"- **{b['text']}**{wait}{dep}")
    else:
        lines.append("- None.")

    return "\n".join(lines)


def build_standup_transcript(data: dict[str, Any]) -> str:
    """Format prompt transcript for LLM generation."""
    lines = [
        f"Daily Standup for: {data['day']}",
        f"Previous working day: {data['previous_day']}",
        "",
        "### Yesterday completed tasks:",
    ]
    if data["yesterday_tasks"]:
        for t in data["yesterday_tasks"]:
            lines.append(f"- {t['text']}")
    else:
        lines.append("- none")

    lines.append(f"\n### Yesterday focus ({fmt_secs(data['yesterday_seconds'])} total):")
    for a in data["yesterday_apps"][:5]:
        lines.append(f"- {a['app_class']}: {fmt_secs(a['seconds'])}")

    if data["yesterday_commits"]:
        lines.append("\n### Yesterday commits:")
        for c in data["yesterday_commits"]:
            lines.append(f"- {c.get('repo', '')}: {c.get('subject', '')}")

    lines.append("\n### Today planned tasks:")
    if data["today_tasks"]:
        for t in data["today_tasks"]:
            lines.append(f"- {t['text']} (priority: {t.get('priority') or 'none'}, due: {t.get('due_date') or 'none'})")
    else:
        lines.append("- none explicitly scheduled")

    lines.append("\n### Blockers & waiting-on items:")
    if data["blockers"]:
        for b in data["blockers"]:
            lines.append(f"- {b['text']} (waiting_for: {b.get('waiting_for')}, blocked_by: {b.get('blocked_by')})")
    else:
        lines.append("- none")

    lines.append(
        "\nFormat this strictly into three Markdown sections:\n"
        "## Yesterday\n"
        "## Today\n"
        "## Blockers\n"
        "Keep bullets concise, professional, and action-oriented."
    )
    return "\n".join(lines)


async def generate_standup(
    db: Database,
    cfg: Config,
    day: str | None = None,
) -> dict[str, Any]:
    """Generate the daily standup."""
    data = collect_standup_data(db, cfg, day=day)

    if cfg.llm.provider == "none":
        md = fallback_standup(data)
        model = "fallback"
    else:
        transcript = build_standup_transcript(data)
        try:
            md, model = await generate_with_llm(transcript, data["day"], cfg)
        except Exception as exc:
            log.info("standup via LLM failed (%s), using fallback", exc)
            md = fallback_standup(data)
            model = "fallback"

    return {
        "day": data["day"],
        "previous_day": data["previous_day"],
        "standup_md": md,
        "model": model,
        "yesterday_tasks": data["yesterday_tasks"],
        "today_tasks": data["today_tasks"],
        "blockers": data["blockers"],
    }
