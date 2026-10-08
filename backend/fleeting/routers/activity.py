"""Activity tracking + daily log endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..activity import aggregate_day, app_blocked
from ..config import expand_path
from ..services import dailylog, standup, weeklylog

router = APIRouter(prefix="/api/activity", tags=["activity"])
daily_router = APIRouter(prefix="/api/daily-log", tags=["daily-log"])


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
    from ..activity import private_until

    return {
        "day": day,
        "paused": st.activity.is_paused() if day == _local_today() else False,
        "private_until": private_until(st.db) if day == _local_today() else None,
        "collector": {
            "running": st.activity.running,
            "enabled": st.cfg.activity.enabled,
            "last_error": st.activity.last_error,
        },
        **agg,
    }


@router.get("/projects")
def activity_projects(
    request: Request, day: str | None = None, include_empty: bool = False
) -> dict:
    """#53 time per project for a day, heaviest first."""
    from ..services.projects import project_seconds

    day = _valid_day(day or _local_today())
    rows = project_seconds(request.app.state.st.db, day, include_empty=include_empty)
    return {"day": day, "projects": rows}


@router.get("/days")
def activity_days(request: Request) -> list[str]:
    return request.app.state.st.db.activity_days()


@router.get("/live")
def live_session(request: Request) -> dict:
    st = request.app.state.st
    from ..activity import private_until

    return {
        "session": st.activity.current_session(),
        "paused": st.activity.is_paused(),
        # #65 the tray sets this; the UI shows it so a pause is never a mystery.
        "private_until": private_until(st.db),
    }


@router.get("/private")
def private_state(request: Request) -> dict:
    """#65 is private mode running, and until when."""
    from ..activity import private_until

    until = private_until(request.app.state.st.db)
    return {"active": until is not None, "until": until}


@router.post("/private")
def start_private(request: Request, body: PrivateIn) -> dict:
    """#65 stop tracking for N minutes without changing the manual switch."""
    until = request.app.state.st.activity.set_private(body.minutes)
    return {"active": True, "until": until}


@router.delete("/private", status_code=204)
def stop_private(request: Request) -> None:
    if not request.app.state.st.activity.clear_private():
        raise HTTPException(status_code=404, detail="private mode was not running")


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


class WindowAskIn(BaseModel):
    # #63 a range dragged on the timeline.
    day: str = Field(min_length=10, max_length=10)
    start: str = Field(min_length=1, max_length=40)
    end: str = Field(min_length=1, max_length=40)
    question: str = Field(default="", max_length=400)


class PrivateIn(BaseModel):
    minutes: int = Field(ge=1, le=1440)


class AppAliasIn(BaseModel):
    from_class: str = Field(min_length=1, max_length=120)
    to_class: str = Field(min_length=1, max_length=120)


@router.get("/apps/aliases")
def app_aliases(request: Request) -> list[dict]:
    """#64 renamed/merged classes."""
    db = request.app.state.st.db
    return [
        {"from_class": k, "to_class": v}
        for k, v in sorted(db.app_aliases().items())
    ]


@router.post("/apps/alias")
def set_app_alias(request: Request, body: AppAliasIn) -> dict:
    """#64 rename or merge an app. Rewrites its history in the same call."""
    from ..activity import set_app_alias as apply_alias

    db = request.app.state.st.db
    try:
        apply_alias(db, body.from_class.strip(), body.to_class.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, **body.model_dump()}


@router.delete("/apps/alias/{from_class}", status_code=204)
def delete_app_alias(request: Request, from_class: str) -> None:
    """Stops future renaming; already-merged history stays merged."""
    from ..activity import delete_app_alias as drop_alias

    if not drop_alias(request.app.state.st.db, from_class):
        raise HTTPException(status_code=404, detail="alias not found")


class AppIdleIn(BaseModel):
    app_class: str = Field(min_length=1, max_length=120)
    idle_min: int = Field(ge=1, le=120)


@router.get("/apps/idle")
def app_idle_rules(request: Request) -> list[dict]:
    """#340 per-app idle thresholds."""
    return [
        {"app_class": k, "idle_min": v}
        for k, v in sorted(request.app.state.st.db.app_idle_rules().items())
    ]


@router.post("/apps/idle")
def set_app_idle(request: Request, body: AppIdleIn) -> dict:
    """Set one app's idle threshold. Also creates its tracing rule if absent."""
    db = request.app.state.st.db
    if body.app_class not in db.app_rules():
        db.set_app_rule(body.app_class, True)
    db.set_app_idle_rule(body.app_class, body.idle_min)
    return {"ok": True, **body.model_dump()}


@router.delete("/apps/idle/{app_class}", status_code=204)
def clear_app_idle(request: Request, app_class: str) -> None:
    db = request.app.state.st.db
    if app_class not in db.app_rules():
        raise HTTPException(status_code=404, detail="no rule for this app")
    db.set_app_idle_rule(app_class, None)
    db.commit()


class RelabelIn(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    # #334 the same PATCH carries a session annotation.
    note: str | None = Field(default=None, max_length=400)


class AnnotateIn(BaseModel):
    # #334 an annotation may be cleared, hence no min_length.
    note: str = Field(max_length=400)


class GapFillIn(BaseModel):
    at: str = Field(min_length=1, max_length=40)
    minutes: int = Field(ge=1, le=1440)
    note: str = Field(min_length=1, max_length=400)


class SplitIn(BaseModel):
    at: str = Field(min_length=1, max_length=40)


class MergeIn(BaseModel):
    ids: list[int] = Field(min_length=2, max_length=100)


@router.get("/sessions/edits")
def session_edit_trail(request: Request, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    """#54 what was last changed, per session."""
    from ..services.session_edit import session_edits as trail

    return trail(request.app.state.st.db, limit)


@router.patch("/sessions/{session_id}")
def relabel_session(request: Request, session_id: int, body: RelabelIn) -> dict:
    """#54 rename, #334 annotate — one PATCH, whichever field is present."""
    from ..services.session_edit import annotate_session, relabel_session as relabel

    db = request.app.state.st.db
    try:
        if body.note is not None:
            return annotate_session(db, session_id, body.note)
        if body.title is None:
            raise ValueError("nothing to change")
        return relabel(db, session_id, body.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions/annotations")
def session_annotations(request: Request, day: str) -> list[dict]:
    from ..services.session_edit import session_annotations as annotated

    return annotated(request.app.state.st.db, _valid_day(day))


@router.get("/export")
def export_activity(
    request: Request,
    format: str = Query("csv", pattern="^(csv|timesheet)$"),
    day: str | None = None,
    day_from: str | None = None,
    day_to: str | None = None,
) -> Response:
    """#342 session rows or a day×project timesheet, as CSV."""
    from ..services import activity_export

    start = _valid_day(day_from) if day_from else None
    end = _valid_day(day_to) if day_to else None
    if day:
        start = end = _valid_day(day)
    sessions = activity_export.sessions_in_range(request.app.state.st.db, start, end)
    if format == "timesheet":
        body = activity_export.render_timesheet_csv(sessions)
    else:
        body = activity_export.render_sessions_csv(sessions)
    name = f"fleeting-{format}-{(end or start or datetime.now().strftime('%Y-%m-%d'))}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/metrics/switches")
def metric_switches(request: Request, day: str | None = None) -> dict:
    """#58 context switches for a day."""
    from ..services.metrics import context_switches

    return context_switches(request.app.state.st.db, _valid_day(day or _local_today()))


@router.get("/metrics/compare")
def metric_compare(
    request: Request, day: str | None = None, window: int = Query(7, ge=1, le=90)
) -> dict:
    """#62 today against the mean of the previous `window` days."""
    from ..services.metrics import today_vs_average

    return today_vs_average(request.app.state.st.db, _valid_day(day or _local_today()), window=window)


@router.get("/metrics/heatmap")
def metric_heatmap(
    request: Request, weeks: int = Query(12, ge=1, le=52), end: str | None = None
) -> dict:
    """#59 calendar grid of active minutes."""
    from ..services.metrics import heatmap

    return heatmap(request.app.state.st.db, weeks=weeks, end=_valid_day(end) if end else None)


@router.post("/ask")
async def ask_about_window(request: Request, body: WindowAskIn) -> dict:
    """#63 what was I doing between these two times?"""
    from ..services.activity_ask import answer_window

    try:
        return await answer_window(
            request.app.state.st.db, request.app.state.st.cfg, body.day, body.start, body.end, body.question
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/timeline")
def activity_timeline(
    request: Request, day: str | None = None, kinds: str = "session,task,note"
) -> dict:
    """#339 what you did, finished and wrote, merged into one feed."""
    from ..services.timeline import day_events

    wanted = tuple(k.strip() for k in kinds.split(",") if k.strip())
    unknown = [k for k in wanted if k not in ("session", "task", "note")]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown kinds: {', '.join(unknown)}")
    day = _valid_day(day or _local_today())
    return {"day": day, "events": day_events(request.app.state.st.db, day, kinds=wanted)}


@router.get("/gaps")
def activity_gaps(
    request: Request, day: str | None = None, min_minutes: int = Query(45, ge=5, le=720)
) -> dict:
    """#337 stretches of the day with nothing recorded in them."""
    from ..services.gaps import day_gaps, gap_summary

    day = _valid_day(day or _local_today())
    gaps = day_gaps(request.app.state.st.db, day, min_minutes=min_minutes)
    return {"day": day, "gaps": gaps, "summary": gap_summary(gaps)}


@router.post("/gaps/fill")
def fill_gap(request: Request, body: GapFillIn) -> dict:
    """#337 record what happened in a gap as a synthetic session."""
    from ..services.gaps import day_gaps, fill_gap as fill

    db = request.app.state.st.db
    day = body.at[:10]
    window = fill(day_gaps(db, day), body.at, body.minutes, body.note)
    if window is None:
        raise HTTPException(status_code=422, detail="that time is not inside a recorded gap")
    cur = db.execute(
        "INSERT INTO activity (app_class, title, first_seen, last_seen, seconds, day, note)"
        " VALUES ('recall', ?, ?, ?, ?, ?, ?)",
        (
            f"gap: {body.note[:80]}",
            window["start"],
            window["end"],
            max(60, body.minutes * 60),
            day,
            body.note,
        ),
    )
    db.commit()
    row = dict(db.execute("SELECT * FROM activity WHERE id = ?", (cur.lastrowid,)).fetchone())
    request.app.state.st.bus.publish("activity.live", row)
    return row


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(request: Request, session_id: int) -> None:
    from ..services.session_edit import delete_session as drop

    if not drop(request.app.state.st.db, session_id):
        raise HTTPException(status_code=404, detail="session not found")


@router.post("/sessions/{session_id}/split")
def split_session(request: Request, session_id: int, body: SplitIn) -> list[dict]:
    from ..services.session_edit import split_session as split

    db = request.app.state.st.db
    try:
        ids = split(db, session_id, body.at)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [dict(db.execute("SELECT * FROM activity WHERE id = ?", (i,)).fetchone()) for i in ids]


@router.post("/sessions/merge")
def merge_sessions(request: Request, body: MergeIn) -> dict:
    from ..services.session_edit import merge_sessions as merge

    db = request.app.state.st.db
    try:
        merged_id = merge(db, body.ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dict(db.execute("SELECT * FROM activity WHERE id = ?", (merged_id,)).fetchone())


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
@daily_router.get("")
def get_daily_log(request: Request, day: str | None = None) -> dict:
    st = request.app.state.st
    day = _valid_day(day or _local_today())
    row = st.db.get_daily_log(day)
    if not row:
        return {"day": day, "summary_md": None, "model": None, "created_at": None, "edited": 0, "evidence": []}
    out = dict(row)
    raw_ev = out.get("evidence")
    if isinstance(raw_ev, str):
        try:
            out["evidence"] = json.loads(raw_ev)
        except Exception:
            out["evidence"] = []
    elif not raw_ev:
        out["evidence"] = []
    return out


@router.put("/daily-log/{day}/edit", response_model=None)
@daily_router.put("/{day}/edit", response_model=None)
def edit_daily_log(request: Request, day: str, body: dict) -> Response | dict:
    st = request.app.state.st
    day = _valid_day(day)
    row = st.db.get_daily_log(day)
    if not row:
        raise HTTPException(404, f"daily log for {day} not found")
    raw_body = body.get("body", "")
    trimmed = raw_body.strip() if isinstance(raw_body, str) else ""
    if not trimmed:
        st.db.clear_daily_log_edit(day)
        dailylog.mirror_to_vault(st.cfg, day, dailylog.effective_body(st.db.get_daily_log(day)))
        st.bus.publish("dailylog.updated", {"day": day})
        return Response(status_code=204)
    st.db.set_daily_log_edit(day, raw_body)
    dailylog.mirror_to_vault(st.cfg, day, raw_body)
    st.bus.publish("dailylog.updated", {"day": day})
    return {"ok": True, "edited": 1, "body": raw_body}


@router.delete("/daily-log/{day}/edit", status_code=204)
@daily_router.delete("/{day}/edit", status_code=204)
def clear_daily_log_edit(request: Request, day: str) -> Response:
    st = request.app.state.st
    day = _valid_day(day)
    row = st.db.get_daily_log(day)
    if not row:
        raise HTTPException(404, f"daily log for {day} not found")
    st.db.clear_daily_log_edit(day)
    dailylog.mirror_to_vault(st.cfg, day, dailylog.effective_body(st.db.get_daily_log(day)))
    st.bus.publish("dailylog.updated", {"day": day})
    return Response(status_code=204)


@router.get("/daily-log/{day}/reflection")
@daily_router.get("/{day}/reflection")
def get_daily_reflection(request: Request, day: str) -> dict:
    st = request.app.state.st
    day = _valid_day(day)
    log_row = st.db.get_daily_log(day)
    report_md = dailylog.effective_body(log_row) if log_row else ""
    prompts = dailylog.get_reflection_prompts(day, report_md)

    existing_rows = st.db.execute(
        """
        SELECT id FROM notes
        WHERE (json_extract(source, '$.day') = :day OR tags LIKE :tag)
          AND tags LIKE '%reflection%'
          AND trashed_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        {"day": day, "tag": f"%daily/{day}%"},
    ).fetchall()

    note_data = st.db.get_note(existing_rows[0]["id"]) if existing_rows else None

    return {
        "day": day,
        "prompts": prompts,
        "note": note_data,
    }


@router.post("/daily-log/{day}/reflection")
@daily_router.post("/{day}/reflection")
def save_daily_reflection(request: Request, day: str, body: dict) -> dict:
    st = request.app.state.st
    day = _valid_day(day)
    text = (body.get("text") or "").strip()
    prompt = (body.get("prompt") or "").strip()
    if not text:
        raise HTTPException(422, "reflection text cannot be empty")

    note_body = (
        f"> **Prompt**: {prompt}\n\n{text}\n\n---\n*Reflecting on Daily Digest for {day}*"
        if prompt
        else f"{text}\n\n---\n*Reflecting on Daily Digest for {day}*"
    )

    note_dict = {
        "type": "note",
        "title": f"Daily Reflection — {day}",
        "raw_text": note_body,
        "summary": text[:200],
        "tags": ["reflection", "daily", f"daily/{day}"],
        "source": {"type": "daily_log", "day": day},
        "status": "done",
    }
    created = st.db.insert_note(note_dict)
    st.bus.publish("note.created", {"id": created["id"]})
    return created


@router.get("/daily-log/{day}/export")
@daily_router.get("/{day}/export")
def export_daily_log(
    request: Request,
    day: str,
    format: str = Query("md", pattern="^(md|markdown|pdf)$"),
) -> Response:
    """#74 Export a report as Markdown or PDF."""
    from ..services import report_export

    st = request.app.state.st
    day = _valid_day(day)
    row = st.db.get_daily_log(day)
    if not row:
        raise HTTPException(404, f"daily log for {day} not found")

    body_md = dailylog.effective_body(row)
    if format in ("md", "markdown"):
        content = report_export.render_markdown_export(day, body_md)
        filename = f"daily-log-{day}.md"
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        pdf_bytes = report_export.render_pdf_export(day, body_md)
        filename = f"daily-log-{day}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.post("/daily-log/generate")
@daily_router.post("/generate")
async def generate_log(request: Request, body: dict) -> dict:
    st = request.app.state.st
    day = _valid_day(str(body.get("day") or _local_today()))
    rolling = bool(body.get("rolling"))
    if rolling:
        # past-24-hours report, stored under today's key
        day = _local_today()
    elif day > _local_today():
        raise HTTPException(422, "cannot generate a log for a future day")
    tone = body.get("tone") or "balanced"
    length = body.get("length") or "medium"
    start_time = body.get("start_time")
    end_time = body.get("end_time")
    highlights_only = bool(body.get("highlights_only"))
    questions_for_tomorrow = bool(body.get("questions_for_tomorrow"))
    custom_sections = body.get("custom_sections")
    prompt_override = body.get("prompt_override")

    lock = getattr(st, "digest_lock", None)
    try:
        gen_kwargs = {
            "rolling": rolling,
            "tone": tone,
            "length": length,
            "start_time": start_time,
            "end_time": end_time,
            "highlights_only": highlights_only,
            "questions_for_tomorrow": questions_for_tomorrow,
            "custom_sections": custom_sections,
            "prompt_override": prompt_override,
        }
        if lock:
            async with lock:
                row = await dailylog.generate_daily_log(st.db, st.cfg, day, **gen_kwargs)
        else:
            row = await dailylog.generate_daily_log(st.db, st.cfg, day, **gen_kwargs)
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
    summary = weeklylog.aggregate_week(st.db, start)
    return {
        "week": start,
        "this_week": weeklylog.current_week_start(),
        "report": st.db.get_weekly_log(start),
        "summary": summary,
        "diff": summary.get("diff"),
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
 
 
@router.get("/standup")
async def get_standup(request: Request, day: str | None = None) -> dict:
    """#69 Standup generator: yesterday, today, blockers."""
    st = request.app.state.st
    return await standup.generate_standup(st.db, st.cfg, day=day)


@router.post("/standup/generate")
async def generate_standup_endpoint(request: Request, body: dict) -> dict:
    """#69 Force regeneration of daily standup."""
    st = request.app.state.st
    day = body.get("day")
    return await standup.generate_standup(st.db, st.cfg, day=day)


@router.post("/standup/save-as-note")
def save_standup_as_note(request: Request, body: dict) -> dict:
    """Save the generated standup as a markdown note."""
    st = request.app.state.st
    day = str(body.get("day") or "")
    md = str(body.get("standup_md") or "").strip()
    if not md:
        raise HTTPException(400, "standup_md cannot be empty")
    title = f"Daily Standup — {day}" if day else "Daily Standup"
    tags = ["standup", "daily"]
    if day:
        tags.append(f"daily/{day}")
    note = st.db.insert_note(
        {
            "title": title,
            "raw_text": md,
            "type": "text",
            "tags": tags,
            "source": {"type": "standup", "day": day},
        }
    )
    st.bus.publish("note.created", {"id": note["id"]})
    return {"ok": True, "note": note}

