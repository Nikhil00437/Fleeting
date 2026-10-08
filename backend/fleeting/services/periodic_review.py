"""#70, #171, #172: Parameterised periodic review generator.

Generates monthly, quarterly and annual ("Wrapped"-style) reviews built from:
- Stored weekly logs within the window
- Stored daily logs
- Activity telemetry (total focus, top apps, active days)
- Completed tasks and git commits
"""

from __future__ import annotations

import calendar
import logging
from datetime import datetime
from typing import Any

from ..config import Config, expand_path
from ..db import Database, _row_to_task
from .dailylog import fmt_secs, generate_with_llm
from .files_activity import collect_git_subjects

log = logging.getLogger("fleeting.periodic_review")


def parse_period(kind: str, period: str) -> tuple[str, str, str]:
    """Parse period key into (start_date, end_date, title)."""
    kind = kind.lower().strip()
    period = period.strip()

    if kind == "month":
        year = int(period[:4])
        month = int(period[5:7])
        _, last_day = calendar.monthrange(year, month)
        start_date = f"{year:04d}-{month:02d}-01"
        end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
        title = f"Monthly Review — {period}"
        return start_date, end_date, title

    if kind == "quarter":
        year = int(period[:4])
        # format 2026-Q3 or 2026-3
        q_str = period.upper().split("Q")[-1].replace("-", "")
        q = int(q_str) if q_str.isdigit() else 1
        q = max(1, min(4, q))
        start_month = (q - 1) * 3 + 1
        end_month = q * 3
        _, last_day = calendar.monthrange(year, end_month)
        start_date = f"{year:04d}-{start_month:02d}-01"
        end_date = f"{year:04d}-{end_month:02d}-{last_day:02d}"
        title = f"Quarterly Review — {period}"
        return start_date, end_date, title

    if kind == "year":
        year = int(period[:4])
        start_date = f"{year:04d}-01-01"
        end_date = f"{year:04d}-12-31"
        title = f"Year in Review ({year}) — Fleeting Wrapped"
        return start_date, end_date, title

    raise ValueError(f"Unknown review kind: {kind}")


def aggregate_review_period(
    db: Database,
    cfg: Config,
    kind: str,
    period: str,
) -> dict[str, Any]:
    """Gather all logs, telemetry and achievements for the requested period."""
    start_date, end_date, title = parse_period(kind, period)

    weekly_logs = db.weekly_logs_between(start_date, end_date)
    daily_logs = db.daily_logs_between(start_date, end_date)

    # Activity telemetry
    sessions = db.execute(
        "SELECT * FROM activity WHERE day >= ? AND day <= ?",
        (start_date, end_date),
    ).fetchall()

    total_seconds = sum(int(s["seconds"] or 0) for s in sessions)
    active_days_set = {s["day"] for s in sessions if int(s["seconds"] or 0) > 0}

    # Busiest day
    day_totals: dict[str, int] = {}
    app_totals: dict[str, int] = {}
    for s in sessions:
        secs = int(s["seconds"] or 0)
        day_totals[s["day"]] = day_totals.get(s["day"], 0) + secs
        app = s["app_class"]
        app_totals[app] = app_totals.get(app, 0) + secs

    busiest_day = max(day_totals.items(), key=lambda x: x[1])[0] if day_totals else None
    busiest_seconds = day_totals[busiest_day] if busiest_day else 0

    top_apps = [
        {"app_class": a, "seconds": s}
        for a, s in sorted(app_totals.items(), key=lambda x: x[1], reverse=True)
        if s > 0
    ]

    # Completed tasks in this timeframe
    task_rows = db.execute(
        "SELECT * FROM tasks WHERE done = 1 AND substr(completed_at, 1, 10) >= ? AND substr(completed_at, 1, 10) <= ? ORDER BY completed_at DESC",
        (start_date, end_date),
    ).fetchall()
    completed_tasks = [_row_to_task(r) for r in task_rows]

    # Commits
    commits: list[dict[str, Any]] = []
    if cfg.activity.watch_dirs:
        try:
            dirs = [expand_path(p.strip()) for p in cfg.activity.watch_dirs.split(",") if p.strip()]
            start_dt = datetime.fromisoformat(f"{start_date}T00:00:00").astimezone()
            end_dt = datetime.fromisoformat(f"{end_date}T23:59:59").astimezone()
            commits = collect_git_subjects(dirs, since=start_dt, until=end_dt)
        except Exception:
            log.warning("review: commit collection failed", exc_info=True)

    return {
        "kind": kind,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "title": title,
        "total_seconds": total_seconds,
        "active_days": len(active_days_set),
        "busiest_day": busiest_day,
        "busiest_seconds": busiest_seconds,
        "top_apps": top_apps,
        "weekly_logs": weekly_logs,
        "daily_logs": daily_logs,
        "completed_tasks": completed_tasks,
        "commits": commits,
    }


def fallback_periodic_review(agg: dict[str, Any]) -> str:
    """Deterministic synthesis for monthly, quarterly, or annual review."""
    kind = agg["kind"]
    total = agg["total_seconds"]
    active = agg["active_days"]

    if kind == "year":
        # #172 Fleeting Wrapped style
        lines = [
            f"# {agg['title']}",
            "",
            "## The Big Numbers",
            f"- **{fmt_secs(total)}** of active focus logged across **{active}** active days.",
            f"- **{len(agg['completed_tasks'])}** tasks checked off.",
            f"- **{len(agg['weekly_logs'])}** weekly digests and **{len(agg['daily_logs'])}** daily digests recorded.",
        ]
        if agg["busiest_day"]:
            lines.append(f"- Busiest single day was **{agg['busiest_day']}** ({fmt_secs(agg['busiest_seconds'])}).")

        lines.extend(["", "## Your Top Tools & Superpowers"])
        if agg["top_apps"]:
            denom = total or 1
            for a in agg["top_apps"][:6]:
                pct = round(a["seconds"] / denom * 100)
                lines.append(f"- **{a['app_class']}**: {fmt_secs(a['seconds'])} ({pct}%)")
        else:
            lines.append("- No dominant tool recorded.")

        lines.extend(["", "## Weekly Highlights Across the Year"])
        if agg["weekly_logs"]:
            for w in agg["weekly_logs"][:12]:
                first_summary = next(
                    (ln.strip() for ln in w["summary_md"].splitlines()[2:] if ln.strip() and not ln.startswith("#")),
                    "Active week.",
                )
                lines.append(f"- **Week of {w['week_start']}**: {first_summary}")
        else:
            lines.append("- No weekly digests recorded for this year.")

        lines.extend(["", "## What Shipped"])
        if agg["completed_tasks"]:
            for t in agg["completed_tasks"][:10]:
                lines.append(f"- Completed: **{t['text']}**")
        if agg["commits"]:
            for c in agg["commits"][:10]:
                lines.append(f"- Commit: [{c.get('repo', '?')}] {c.get('subject', '')}")
        if not agg["completed_tasks"] and not agg["commits"]:
            lines.append("- No completed tasks recorded.")

        return "\n".join(lines)

    if kind == "quarter":
        # #171 Quarterly review
        lines = [
            f"# {agg['title']}",
            "",
            "## Executive Summary",
            f"Over this quarter, you tracked **{fmt_secs(total)}** of focus across **{active}** active days.",
            f"You completed **{len(agg['completed_tasks'])}** tasks and logged **{len(agg['weekly_logs'])}** weekly milestones.",
        ]

        lines.extend(["", "## Focus by Tool"])
        if agg["top_apps"]:
            denom = total or 1
            for a in agg["top_apps"][:5]:
                pct = round(a["seconds"] / denom * 100)
                lines.append(f"- **{a['app_class']}**: {fmt_secs(a['seconds'])} ({pct}%)")
        else:
            lines.append("- None.")

        lines.extend(["", "## Weekly Progression"])
        if agg["weekly_logs"]:
            for w in agg["weekly_logs"]:
                summary_line = next(
                    (ln.strip() for ln in w["summary_md"].splitlines()[2:] if ln.strip() and not ln.startswith("#")),
                    "Milestones reached.",
                )
                lines.append(f"- **Week of {w['week_start']}**: {summary_line}")
        else:
            lines.append("- No weekly digests recorded in this quarter.")

        lines.extend(["", "## Accomplishments"])
        if agg["completed_tasks"]:
            for t in agg["completed_tasks"][:8]:
                lines.append(f"- **{t['text']}**")
        else:
            lines.append("- None recorded.")

        return "\n".join(lines)

    # Monthly review
    lines = [
        f"# {agg['title']}",
        "",
        "## Month at a Glance",
        f"Logged **{fmt_secs(total)}** of active focus across **{active}** active days.",
        f"Completed **{len(agg['completed_tasks'])}** tasks.",
    ]

    lines.extend(["", "## Tools & Focus"])
    if agg["top_apps"]:
        denom = total or 1
        for a in agg["top_apps"][:5]:
            pct = round(a["seconds"] / denom * 100)
            lines.append(f"- **{a['app_class']}**: {fmt_secs(a['seconds'])} ({pct}%)")
    else:
        lines.append("- None.")

    lines.extend(["", "## Weekly Digests"])
    if agg["weekly_logs"]:
        for w in agg["weekly_logs"]:
            summary_line = next(
                (ln.strip() for ln in w["summary_md"].splitlines()[2:] if ln.strip() and not ln.startswith("#")),
                "Logged milestones.",
            )
            lines.append(f"- **Week of {w['week_start']}**: {summary_line}")
    else:
        lines.append("- No weekly summaries written during this month.")

    lines.extend(["", "## Accomplishments"])
    if agg["completed_tasks"]:
        for t in agg["completed_tasks"][:8]:
            lines.append(f"- **{t['text']}**")
    else:
        lines.append("- None recorded.")

    return "\n".join(lines)


def build_periodic_review_transcript(agg: dict[str, Any]) -> str:
    """Format prompt transcript for periodic review LLM generation."""
    lines = [
        f"Periodic Review: {agg['title']}",
        f"Timeframe: {agg['start_date']} to {agg['end_date']}",
        f"Total active screentime: {fmt_secs(agg['total_seconds'])} across {agg['active_days']} days.",
        "",
        "### Top tools:",
    ]
    for a in agg["top_apps"][:8]:
        lines.append(f"- {a['app_class']}: {fmt_secs(a['seconds'])}")

    lines.append("\n### Stored Weekly Digests:")
    if agg["weekly_logs"]:
        for w in agg["weekly_logs"]:
            lines.append(f"#### Week {w['week_start']}")
            lines.append(w["summary_md"][:1200])
    else:
        lines.append("- none")

    lines.append("\n### Stored Daily Digests:")
    if agg["daily_logs"]:
        for d in agg["daily_logs"][:15]:
            lines.append(f"- {d['day']}: {d['summary_md'][:300]}")
    else:
        lines.append("- none")

    lines.append("\n### Key Completed Tasks:")
    if agg["completed_tasks"]:
        for t in agg["completed_tasks"][:20]:
            lines.append(f"- {t['text']}")
    else:
        lines.append("- none")

    lines.append(
        "\nSynthesize this into a cohesive, high-level review report in Markdown.\n"
        "Focus on accomplishments, trajectories, habits and tool distribution."
    )
    return "\n".join(lines)


async def generate_periodic_review(
    db: Database,
    cfg: Config,
    kind: str,
    period: str,
) -> dict[str, Any]:
    """Generate periodic review for month, quarter, or year."""
    agg = aggregate_review_period(db, cfg, kind, period)

    if cfg.llm.provider == "none":
        md = fallback_periodic_review(agg)
        model = "fallback"
    else:
        transcript = build_periodic_review_transcript(agg)
        try:
            md, model = await generate_with_llm(transcript, agg["period"], cfg)
        except Exception as exc:
            log.info("periodic review via LLM failed (%s), using fallback", exc)
            md = fallback_periodic_review(agg)
            model = "fallback"

    return {
        "kind": agg["kind"],
        "period": agg["period"],
        "start_date": agg["start_date"],
        "end_date": agg["end_date"],
        "title": agg["title"],
        "review_md": md,
        "model": model,
        "metrics": {
            "total_seconds": agg["total_seconds"],
            "active_days": agg["active_days"],
            "busiest_day": agg["busiest_day"],
            "weekly_logs_count": len(agg["weekly_logs"]),
            "daily_logs_count": len(agg["daily_logs"]),
            "completed_tasks_count": len(agg["completed_tasks"]),
            "top_apps": agg["top_apps"][:5],
        },
    }
