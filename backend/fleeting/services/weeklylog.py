"""Weekly digest — a week-shaped view of what the daily log records.

The daily report covers 24 hours. Seven of them read as seven disconnected
reports; what a weekly summary has to add is the *shape* of the week: which days
were heavy, what carried over, what never got finished.

Built on the existing daily machinery rather than beside it: the same window
sessions, the stored daily summaries (which are the richest input — they are
already LLM-written prose), the week's captures and the open task list. Degrades
to a deterministic digest when the LLM is unreachable, exactly like the daily
one.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from ..config import Config, expand_path
from ..db import Database
from ..events import EventBus
from .dailylog import fmt_secs, generate_with_llm
from .files_activity import collect_git_subjects

log = logging.getLogger("fleeting.weeklylog")

MAX_TRANSCRIPT_CHARS = 12_000
# Sessions below this are tab-switch noise; the daily digest uses the same cut.
MIN_SESSION_SECONDS = 60


# ---------------------------------------------------------------------------
# week arithmetic
# ---------------------------------------------------------------------------


def week_start_for(d: date) -> str:
    """Monday of `d`'s week, as YYYY-MM-DD."""
    return (d - timedelta(days=d.weekday())).isoformat()


def week_days(week_start: str) -> list[str]:
    """The seven day-keys of the week beginning at `week_start`."""
    start = date.fromisoformat(week_start)
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


def current_week_start() -> str:
    return week_start_for(datetime.now().astimezone().date())


def previous_week_start() -> str:
    return week_start_for(datetime.now().astimezone().date() - timedelta(days=7))


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def compute_weekly_diff(
    db: Database,
    week_start: str,
    curr_agg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate focus delta versus the previous week with a plain-English narrative."""
    curr = curr_agg if curr_agg is not None else aggregate_week(db, week_start, include_diff=False)
    start_d = date.fromisoformat(week_start)
    prev_week_start = (start_d - timedelta(days=7)).isoformat()
    prev = aggregate_week(db, prev_week_start, include_diff=False)

    curr_secs = curr["total_seconds"]
    prev_secs = prev["total_seconds"]
    delta_secs = curr_secs - prev_secs

    delta_pct: float | None = None
    if prev_secs > 0:
        delta_pct = round((delta_secs / prev_secs) * 100, 1)

    curr_busy = len([d for d in curr["days"] if d["busy"]])
    prev_busy = len([d for d in prev["days"] if d["busy"]])

    curr_apps = {a["app_class"]: a["seconds"] for a in curr["apps"]}
    prev_apps = {a["app_class"]: a["seconds"] for a in prev["apps"]}
    all_app_names = set(curr_apps.keys()) | set(prev_apps.keys())

    shifts = []
    for app in all_app_names:
        c_sec = curr_apps.get(app, 0)
        p_sec = prev_apps.get(app, 0)
        d_sec = c_sec - p_sec
        if abs(d_sec) >= MIN_SESSION_SECONDS:
            shifts.append(
                {
                    "app_class": app,
                    "delta_seconds": d_sec,
                    "current_seconds": c_sec,
                    "previous_seconds": p_sec,
                }
            )
    shifts.sort(key=lambda s: abs(s["delta_seconds"]), reverse=True)

    if curr_secs == 0 and prev_secs == 0:
        narrative = "No tracked activity recorded this week or last week."
    elif prev_secs == 0 and curr_secs > 0:
        narrative = (
            f"Logged {fmt_secs(curr_secs)} across {curr_busy} active day(s) "
            "(no activity tracked last week to compare)."
        )
    elif curr_secs == 0 and prev_secs > 0:
        narrative = (
            f"No tracked activity this week, down from {fmt_secs(prev_secs)} "
            f"across {prev_busy} active day(s) last week."
        )
    else:
        if delta_secs > 0:
            pct_s = f"+{round(delta_pct):.0f}%" if delta_pct is not None else ""
            diff_s = f"(+{fmt_secs(delta_secs)})"
            prefix = (
                f"Focus was up {pct_s} {diff_s} compared to last week "
                f"({fmt_secs(curr_secs)} vs {fmt_secs(prev_secs)} across {curr_busy} active day(s))."
            ).replace("  ", " ")
        elif delta_secs < 0:
            pct_s = f"{round(delta_pct):.0f}%" if delta_pct is not None else ""
            diff_s = f"(-{fmt_secs(abs(delta_secs))})"
            prefix = (
                f"Focus was down {pct_s} {diff_s} compared to last week "
                f"({fmt_secs(curr_secs)} vs {fmt_secs(prev_secs)} across {curr_busy} active day(s))."
            ).replace("  ", " ")
        else:
            prefix = (
                f"Focus was unchanged compared to last week "
                f"({fmt_secs(curr_secs)} across {curr_busy} active day(s))."
            )

        increases = [s for s in shifts if s["delta_seconds"] > 0]
        decreases = [s for s in shifts if s["delta_seconds"] < 0]
        app_notes = []
        if increases:
            top_inc = increases[0]
            app_notes.append(f"time in {top_inc['app_class']} increased by {fmt_secs(top_inc['delta_seconds'])}")
        if decreases:
            top_dec = decreases[0]
            app_notes.append(f"{top_dec['app_class']} decreased by {fmt_secs(abs(top_dec['delta_seconds']))}")

        if app_notes:
            narrative = f"{prefix} Most notably, {', while '.join(app_notes)}."
        else:
            narrative = prefix

    return {
        "current_week": week_start,
        "previous_week": prev_week_start,
        "current_seconds": curr_secs,
        "previous_seconds": prev_secs,
        "delta_seconds": delta_secs,
        "delta_pct": delta_pct,
        "current_active_days": curr_busy,
        "previous_active_days": prev_busy,
        "app_shifts": shifts,
        "narrative": narrative,
    }


def aggregate_week(
    db: Database,
    week_start: str,
    *,
    include_diff: bool = True,
) -> dict[str, Any]:
    """Collect everything the week report is built from.

    Every one of the seven days appears in `days`, including idle ones: a gap
    in the data should read as "nothing happened", not as a missing day.
    """
    days = week_days(week_start)
    first, last = days[0], days[-1]

    per_day: dict[str, int] = {d: 0 for d in days}
    per_app: dict[str, int] = {}
    for day in days:
        for s in db.activity_sessions(day):
            secs = int(s.get("seconds") or 0)
            per_day[day] += secs
            per_app[s["app_class"]] = per_app.get(s["app_class"], 0) + secs

    day_rows = [
        {"day": d, "seconds": per_day[d], "busy": per_day[d] >= MIN_SESSION_SECONDS}
        for d in days
    ]
    busiest = max(day_rows, key=lambda r: r["seconds"])
    app_rows = [
        {"app_class": a, "seconds": s} for a, s in per_app.items() if s > 0
    ]
    app_rows.sort(key=lambda r: r["seconds"], reverse=True)

    counts = db.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN done = 0 THEN 1 ELSE 0 END) AS open_ "
        "FROM tasks"
    ).fetchone()
    total_tasks = int(counts["total"] or 0)
    open_tasks = int(counts["open_"] or 0)

    res: dict[str, Any] = {
        "week_start": first,
        "week_end": last,
        "days": day_rows,
        "apps": app_rows,
        "total_seconds": sum(per_day.values()),
        "busiest_day": busiest["day"] if busiest["seconds"] > 0 else None,
        "quietest_day": min(day_rows, key=lambda r: r["seconds"])["day"],
        "daily_logs": db.daily_logs_between(first, last),
        "total_tasks": total_tasks,
        "open_tasks": open_tasks,
        "commits": [],
        "files_touched": 0,
    }
    if include_diff:
        res["diff"] = compute_weekly_diff(db, week_start, curr_agg=res)
    return res


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def _day_bar(seconds: int, width: int = 24) -> str:
    if seconds <= 0:
        return ""
    filled = max(1, round((seconds / (8 * 3600)) * width))
    return "█" * min(width, filled)


def build_transcript(agg: dict[str, Any]) -> str:
    """Compact, LLM-friendly rendering of the week."""
    lines = [
        f"Week: {agg['week_start']} → {agg['week_end']} (local time)",
        "",
        "## Time per day",
    ]
    for row in agg["days"]:
        bar = _day_bar(row["seconds"])
        lines.append(f"- {row['day']}  {fmt_secs(row['seconds']):>9}  {bar}")

    lines += ["", "## Time by app"]
    if agg["apps"]:
        total = agg["total_seconds"] or 1
        for a in agg["apps"][:12]:
            pct = round(a["seconds"] / total * 100)
            lines.append(f"- {a['app_class']}  {fmt_secs(a['seconds'])}  ({pct}%)")
    else:
        lines.append("- none")

    if agg["commits"]:
        lines += ["", "## Commits"]
        for c in agg["commits"][:40]:
            lines.append(f"- {c.get('repo', '?')}: {c.get('subject', '')}")

    if agg["daily_logs"]:
        lines += ["", "## Daily summaries already written"]
        for row in agg["daily_logs"]:
            lines += [f"### {row['day']}", row["summary_md"][:1800], ""]

    lines += [
        "",
        "## Open tasks carried into the next week",
        f"{agg['open_tasks']} open of {agg['total_tasks']} total.",
    ]

    if agg.get("diff") and agg["diff"].get("narrative"):
        lines += ["", "## Focus vs. Last Week", agg["diff"]["narrative"]]

    transcript = "\n".join(lines)
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n… (truncated)"
    return transcript


def fallback_weekly_digest(agg: dict[str, Any], week_start: str) -> str:
    """Deterministic synthesis for when no LLM is reachable.

    Human-readable durations throughout, and it says plainly when there is
    nothing. Unlike the daily fallback, idle days *do* render as "0m": a week is
    seven bars wide, and dropping the empty ones would hide the very shape the
    summary exists to show.
    """
    lines = [
        f"# Weekly Digest — {agg['week_start']} → {agg['week_end']}",
        "",
        "## Executive Summary",
        "",
    ]
    if agg["total_seconds"] == 0 and not agg["daily_logs"]:
        lines.append("No tracked activity recorded this week.")
        return "\n".join(lines)

    total = agg["total_seconds"]
    busy_days = [d for d in agg["days"] if d["busy"]]
    top = agg["apps"][:3]
    top_phrase = (
        ", ".join(f"**{a['app_class']}** ({fmt_secs(a['seconds'])})" for a in top)
        if top
        else "no dominant app"
    )
    lines.append(
        f"Logged **{fmt_secs(total)}** of active focus across {len(busy_days)} "
        f"day(s), led by {top_phrase}."
    )
    if agg["busiest_day"]:
        lines.append(
            f"Busiest day was **{agg['busiest_day']}** "
            f"({fmt_secs(next(d['seconds'] for d in agg['days'] if d['day'] == agg['busiest_day']))})."
        )

    lines += ["", "## Time per day", ""]
    for row in agg["days"]:
        bar = _day_bar(row["seconds"], 20)
        lines.append(f"- `{row['day']}` {fmt_secs(row['seconds']):>9}  {bar}")

    if agg["apps"]:
        lines += ["", "## Where the time went", ""]
        denom = total or 1
        for a in agg["apps"][:10]:
            pct = round(a["seconds"] / denom * 100)
            bar = "█" * max(1, round(pct / 5))
            lines.append(f"- {a['app_class']:<24} {fmt_secs(a['seconds']):>9}  {pct:>3}%  {bar}")

    if agg["daily_logs"]:
        lines += ["", "## Daily notes", ""]
        for row in agg["daily_logs"]:
            first_line = next(
                (ln.strip() for ln in row["summary_md"].splitlines()[2:] if ln.strip()),
                "",
            )
            if first_line:
                lines.append(f"- **{row['day']}** — {first_line}")

    if agg.get("diff") and agg["diff"].get("narrative"):
        lines += [
            "",
            "## Focus vs. Last Week",
            "",
            agg["diff"]["narrative"],
        ]

    lines += [
        "",
        "## Still open",
        "",
        f"{agg['open_tasks']} of {agg['total_tasks']} tasks remain open.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------


async def generate_weekly_log(
    db: Database,
    cfg: Config,
    week_start: str | None = None,
    *,
    bus: EventBus | None = None,
    include_commits: bool = True,
) -> dict[str, Any]:
    """Generate (or regenerate) the weekly report. Returns the stored row.

    Refuses an empty week rather than storing a contentless report that reads
    like a real one.
    """
    week_start = week_start or previous_week_start()
    agg = aggregate_week(db, week_start)

    if include_commits and cfg.activity.watch_dirs:
        try:
            dirs = [
                expand_path(p.strip())
                for p in cfg.activity.watch_dirs.split(",")
                if p.strip()
            ]
            start = datetime.fromisoformat(f"{agg['week_start']}T00:00:00").astimezone()
            agg["commits"] = collect_git_subjects(dirs, since=start, until=start + timedelta(days=7))
        except Exception:
            # Commits are a bonus; the rest of the report is still useful.
            log.warning("weekly log: commit collection failed", exc_info=True)

    if (
        agg["total_seconds"] == 0
        and not agg["daily_logs"]
        and not agg["commits"]
    ):
        raise ValueError(f"no tracked activity in the week of {week_start}")

    try:
        from .search import persist_commits

        persist_commits(db, agg["commits"])
    except Exception:
        log.warning("weekly log: could not persist commits for search", exc_info=True)

    transcript = build_transcript(agg)
    try:
        md, model = await generate_with_llm(transcript, week_start, cfg)
    except Exception as exc:
        log.info("weekly log via LLM unavailable (%s) — using fallback digest", exc)
        md, model = fallback_weekly_digest(agg, week_start), "fallback"

    db.upsert_weekly_log(week_start, md, model)
    row = db.get_weekly_log(week_start)
    if bus is not None:
        bus.publish(
            "weekly.updated",
            {"week": week_start, "kind": "weekly-report", "model": model},
        )
    return row
