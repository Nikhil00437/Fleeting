"""Activity tracking + daily log endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..activity import aggregate_day, app_blocked
from ..config import expand_path
from ..services import dailylog, weeklylog

router = APIRouter(prefix="/api/activity", tags=["activity"])


def _local_today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _valid_day(day: str) -> str:
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")
    return day


@router.get("/day")
def activity_day(request: Request, day: str | None = None) -> dict:
    st = request.app.state.st
    day = _valid_day(day or _local_today())
    sessions = [
        s for s in st.db.activity_sessions(day)
        if not app_blocked(st.cfg.activity, st.db, s["app_class"])
    ]
    agg = aggregate_day(sessions)
    return {
        "day": day,
        "paused": st.activity.is_paused() if day == _local_today() else False,
        "collector": {
            "running": st.activity.running,
            "enabled": st.cfg.activity.enabled,
            "last_error": st.activity.last_error,
        },
        **agg,
    }


@router.get("/days")
def activity_days(request: Request) -> list[str]:
    return request.app.state.st.db.activity_days()


@router.get("/live")
def live_session(request: Request) -> dict:
    st = request.app.state.st
    return {"session": st.activity.current_session(), "paused": st.activity.is_paused()}


@router.post("/pause")
def set_pause(request: Request, body: dict) -> dict:
    st = request.app.state.st
    paused = bool(body.get("paused"))
    st.activity.set_paused(paused)
    return {"paused": st.activity.is_paused()}


@router.get("/apps")
def known_apps(request: Request) -> list[dict]:
    """All apps seen on this machine with their effective per-app tracking state."""
    from ..activity import app_blocked

    st = request.app.state.st
    out = []
    for row in st.db.known_apps():
        if not row["has_rule"]:
            row["tracked"] = not app_blocked(st.cfg.activity, st.db, row["app_class"])
        out.append(row)
    return out


@router.post("/apps/tracked")
def set_app_tracked(request: Request, body: dict) -> dict:
    """Enable/disable tracing for one app individually."""
    st = request.app.state.st
    app_class = str(body.get("app_class") or "").strip()
    tracked = bool(body.get("tracked"))
    if not app_class:
        raise HTTPException(422, "app_class is required")
    st.db.set_app_rule(app_class, tracked)
    return {"app_class": app_class, "tracked": tracked}


@router.get("/week")
def activity_week(request: Request, days: int = 7) -> list[dict]:
    """Tracked seconds per local day for the last N days (chart data)."""
    st = request.app.state.st
    return st.db.activity_per_day(min(max(days, 2), 60))


@router.get("/files")
def files_activity(request: Request, hours: float = 24.0) -> dict:
    """Recently modified files + git commit subjects (metadata only)."""
    from datetime import timedelta

    from ..services.files_activity import (
        collect_git_subjects,
        scan_recent_files,
    )

    st = request.app.state.st
    hours = min(max(hours, 1.0), 168.0)
    since = datetime.now().astimezone() - timedelta(hours=hours)
    watch_dirs = [
        expand_path(p.strip()) for p in st.cfg.activity.watch_dirs.split(",") if p.strip()
    ]
    return {
        "since": since.isoformat(timespec="seconds"),
        **scan_recent_files(watch_dirs, since=since),
        "git": collect_git_subjects(watch_dirs, since=since),
    }


@router.get("/daily-log")
def get_daily_log(request: Request, day: str | None = None) -> dict:
    st = request.app.state.st
    day = _valid_day(day or _local_today())
    row = st.db.get_daily_log(day)
    if not row:
        return {"day": day, "summary_md": None, "model": None, "created_at": None}
    return row


@router.post("/daily-log/generate")
async def generate_log(request: Request, body: dict) -> dict:
    st = request.app.state.st
    day = _valid_day(str(body.get("day") or _local_today()))
    rolling = bool(body.get("rolling"))
    if rolling:
        # past-24-hours report, stored under today's key
        day = _local_today()
    elif day > _local_today():
        raise HTTPException(422, "cannot generate a log for a future day")
    lock = getattr(st, "digest_lock", None)
    try:
        if lock:
            async with lock:
                row = await dailylog.generate_daily_log(st.db, st.cfg, day, rolling=rolling)
        else:
            row = await dailylog.generate_daily_log(st.db, st.cfg, day, rolling=rolling)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if rolling and day == _local_today():
        if hasattr(st, "activity") and st.activity:
            total_seconds = st.activity.today_screentime_seconds()
        else:
            sessions = [
                s for s in st.db.activity_sessions(day)
                if not app_blocked(st.cfg.activity, st.db, s["app_class"])
            ]
            total_seconds = sum(s.get("seconds", 0) for s in sessions)
        st.db.kv_set(f"digest_screentime_hours_{day}", str(total_seconds // 3600))
    st.bus.publish("dailylog.updated", {"day": day, "kind": "daily-report" if rolling else "day-log"})
    return row


@router.post("/daily-log/generate-yesterday-if-missing")
async def generate_yesterday(request: Request) -> dict:
    """Convenience for midnight automation; skips if already generated."""
    st = request.app.state.st
    yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")
    if st.db.get_daily_log(yesterday):
        return {"ok": True, "skipped": True, "day": yesterday}
    if not st.db.activity_sessions(yesterday):
        return {"ok": True, "skipped": True, "day": yesterday}
    row = await dailylog.generate_daily_log(st.db, st.cfg, yesterday)
    st.bus.publish("dailylog.updated", {"day": yesterday})
    return {**row, "skipped": False}


def _valid_week(week: str | None) -> str:
    """Validate a week-start key and snap it to its Monday."""
    from ..services.weeklylog import week_start_for

    raw = week or weeklylog.previous_week_start()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, "week must be YYYY-MM-DD")
    return week_start_for(parsed.date())


@router.get("/weekly-log")
def get_weekly_log(request: Request, week: str | None = None) -> dict:
    """The finished week's report plus its shape, so the UI can chart either."""
    st = request.app.state.st
    start = _valid_week(week)
    return {
        "week": start,
        "this_week": weeklylog.current_week_start(),
        "report": st.db.get_weekly_log(start),
        "summary": weeklylog.aggregate_week(st.db, start),
    }


@router.post("/weekly-log/generate")
async def generate_weekly(request: Request, body: dict) -> dict:
    st = request.app.state.st
    start = _valid_week(str(body.get("week") or "") or None)
    lock = getattr(st, "digest_lock", None)
    try:
        if lock:
            async with lock:
                row = await weeklylog.generate_weekly_log(
                    st.db, st.cfg, start, bus=st.bus
                )
        else:
            row = await weeklylog.generate_weekly_log(st.db, st.cfg, start, bus=st.bus)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"report": row, "week": start}


@router.post("/weekly-log/generate-previous-if-missing")
async def generate_previous_weekly(request: Request) -> dict:
    """Monday-morning automation; skips when already written."""
    st = request.app.state.st
    start = weeklylog.previous_week_start()
    if st.db.get_weekly_log(start):
        return {"ok": True, "skipped": True, "week": start}
    try:
        row = await weeklylog.generate_weekly_log(st.db, st.cfg, start, bus=st.bus)
    except ValueError:
        return {"ok": True, "skipped": True, "week": start}
    return {"ok": True, "skipped": False, "week": start, "report": row}
