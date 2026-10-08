"""Dedicated Task REST API endpoints with atomic CRUD, toggle, and SSE events."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import (
    FocusIn,
    QuickAddIn,
    QuickAddOut,
    QuickAddParseView,
    StreakOut,
    TaskCreateIn,
    TaskExportIn,
    TaskExportOut,
    TaskOut,
    WeeklyReview,
    TaskUpdateIn,
    TodayOut,
    WeekPlan,
)
from ..services import calendar_svc, llm, markdown, task_export, whatnow
from ..services.calendar_svc import date_tag
from ..services.planner import plan_week
from ..services.repos import discover_git_repos
from ..services.task_text import parse_quick_add

log = logging.getLogger("fleeting.tasks")

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _sync_vault_and_notify_note(st: Any, note_id: str | None) -> None:
    """Sync parent note markdown vault file and notify UI subscribers."""
    if not note_id:
        return
    note = st.db.get_note(note_id)
    if not note:
        return
    if note.get("status") == "done":
        try:
            markdown.sync_note(st.cfg.paths, note)
        except Exception:
            log.warning("failed to sync note %s to vault", note_id, exc_info=True)
    st.bus.publish("note.updated", note)


@router.get("", response_model=list[TaskOut])
@router.get("/", response_model=list[TaskOut], include_in_schema=False)
def list_tasks(
    request: Request,
    status: str = Query("open", description="Task status filter ('open' | 'done' | 'all')"),
    priority: str | None = Query(None, description="Priority filter ('P1' | 'P2' | 'P3')"),
    repo: str | None = Query(None, description="Repository filter"),
    due: str | None = Query(None, description="Due date filter ('overdue' | 'today' | 'week' | 'nodate')"),
    q: str | None = Query(None, description="Search query across text and note title"),
    list: str | None = Query(None, description="List filter ('inbox' | 'someday'); default inbox only"),
    context: str | None = Query(None, description="@context filter (#283)"),
    waiting: bool | None = Query(None, description="Waiting-for filter (#281)"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_done: bool | None = Query(None, description="Backward compatibility parameter"),
) -> list[TaskOut]:
    st = request.app.state.st
    effective_status = status
    if include_done is True:
        effective_status = "all"

    tasks = st.db.list_tasks(
        status=effective_status,
        priority=priority,
        repo=repo,
        due=due,
        q=q,
        list=list,
        context=context,
        waiting=waiting,
        limit=limit,
        offset=offset,
    )
    return [TaskOut(**t) for t in tasks]


@router.post("", response_model=TaskOut)
@router.post("/", response_model=TaskOut, include_in_schema=False)
async def create_task(body: TaskCreateIn, request: Request) -> TaskOut:
    # async so #31 can schedule background priority inference; the Database
    # is thread-local by design, so serving this off the loop is harmless.
    st = request.app.state.st
    if body.note_id:
        note = st.db.get_note(body.note_id)
        if not note:
            raise HTTPException(404, f"note {body.note_id} not found")

    task_data = body.model_dump(exclude_unset=True)
    try:
        task = st.db.insert_task(task_data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    st.bus.publish("task.created", task)
    _sync_vault_and_notify_note(st, task["note_id"])
    # #31: only rank tasks whose priority nobody chose.
    if task.get("priority_source") != "manual" and task["priority"] == "P2":
        asyncio.create_task(_infer_priority_after_create(st, task))
    return TaskOut(**task)


async def _infer_priority_after_create(st: Any, task: dict) -> None:
    """#31: rank a newly created task in the background.

    The request already returned — capture must stay instant — so inference
    lands as a second event. `priority_source='inferred'` records that the
    model chose this, which is what lets a later manual edit lock it (#31's
    "override that sticks").
    """
    task_id = task["id"]
    try:
        priority = await llm.infer_priority(task["text"], st.cfg.llm)
    except Exception:  # never let a ranking hiccup surface as a capture error
        log.warning("priority inference failed for task %s", task_id, exc_info=True)
        return
    if priority is None:
        return
    current = st.db.get_task(task_id)
    if current is None or current.get("priority_source") == "manual":
        return  # the user re-ranked it while the model was thinking
    updated = st.db.update_task(task_id, {"priority": priority, "priority_source": "inferred"})
    if updated:
        st.bus.publish("task.updated", updated)


@router.post("/quick-add", response_model=QuickAddOut)
def quick_add_task(body: QuickAddIn, request: Request) -> QuickAddOut:
    """#278: natural-language quick-add. The parser lifts what it recognises
    out of the text; explicitly provided fields win over parsed ones."""
    st = request.app.state.st
    parsed = parse_quick_add(body.text)

    task_data = {
        "text": parsed.text or body.text,
        "list": body.list,
        "due_date": body.due_date or parsed.due_date,
        "priority": body.priority or parsed.priority or "P2",
        "repo": body.repo or parsed.repo,
        "context": body.context or parsed.context,
    }
    if body.note_id:
        task_data["note_id"] = body.note_id

    try:
        task = st.db.insert_task(task_data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    st.bus.publish("task.created", task)
    _sync_vault_and_notify_note(st, task.get("note_id"))
    return QuickAddOut(
        task=TaskOut(**task),
        parsed=QuickAddParseView(
            text=parsed.text,
            due_date=parsed.due_date,
            context=parsed.context,
            repo=parsed.repo,
            priority=parsed.priority,
        ),
    )


@router.get("/today", response_model=TodayOut)
def get_today(request: Request) -> TodayOut:
    """#30/#33: the day's work and the next action, one ranking for both."""
    st = request.app.state.st
    from ..db import datetime_now_local

    now = datetime_now_local()
    current_session = st.activity.current_session() if st.activity else None
    current_title = None
    if current_session:
        # Window titles carry repo names and often context words — the one
        # signal #33's ranking borrows from "recent activity".
        current_title = " ".join(
            x for x in (current_session.get("app_class"), current_session.get("title")) if x
        )
    tasks = st.db.list_tasks(status="all", limit=1000)
    result = whatnow.build_today(
        tasks,
        now=now,
        capacity_min=st.cfg.tasks.daily_capacity_min,
        current_title=current_title,
    )
    return TodayOut(
        day=result["day"],
        overdue=[TaskOut(**t) for t in result["overdue"]],
        due_today=[TaskOut(**t) for t in result["due_today"]],
        waiting=[TaskOut(**t) for t in result["waiting"]],
        completed_today=[TaskOut(**t) for t in result["completed_today"]],
        next_action=TaskOut(**result["next_action"]) if result["next_action"] else None,
        up_next=[TaskOut(**t) for t in result["up_next"]],
        load=result["load"],
        streak=StreakOut(**whatnow.build_streaks(tasks, now=now)),
    )


@router.post("/export", response_model=TaskExportOut)
def export_tasks(body: TaskExportIn, request: Request) -> TaskExportOut:
    """#40: render every task as todo.txt or a Markdown checklist.

    Always returns the text; when the vault is enabled it is also written
    next to the notes so the checklist is browsable like everything else.
    """
    st = request.app.state.st
    from ..config import expand_path

    today = calendar_svc.today(calendar_svc.current_tz()).isoformat()
    all_tasks = st.db.list_tasks(status="all", limit=2000)
    open_tasks = [t for t in all_tasks if not t["done"] and t.get("list", "inbox") == "inbox"]
    done = [t for t in all_tasks if t["done"]] if body.include_done else []

    if body.format == "todo":
        content = task_export.render_todo_txt(open_tasks, done)
        filename = "todo.txt"
    else:
        content = task_export.render_markdown(open_tasks, done, day=today)
        filename = "Tasks.md"

    path: str | None = None
    if st.cfg.paths.vault_sync:
        try:
            vault = expand_path(st.cfg.paths.vault_dir)
            vault.mkdir(parents=True, exist_ok=True)
            target = vault / filename
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(target)
            path = str(target)
        except OSError as exc:
            log.warning("task export could not be written to the vault: %s", exc)
    return TaskExportOut(content=content, filename=filename, path=path)


@router.get("/review", response_model=WeeklyReview)
def get_weekly_review(request: Request) -> WeeklyReview:
    """#38: the weekly review ritual's input — what needs a decision.

    Split into three piles: work that was due before this week and is still
    open (carry it or drop it), work due inside the week, and what actually
    landed. The UI decides; this only sorts, so the screen and any future
    reminder agree on what "slipped" means.
    """
    st = request.app.state.st
    from ..db import datetime_now_local

    now = datetime_now_local()
    today = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    tasks = st.db.list_tasks(status="all", limit=1000)
    open_tasks = [t for t in tasks if not t["done"] and t.get("list", "inbox") == "inbox"]
    carry_over = sorted(
        [t for t in open_tasks if t.get("due_date") and t["due_date"] < week_start],
        key=lambda t: (t["due_date"], t["priority"]),
    )
    this_week = sorted(
        [t for t in open_tasks if t.get("due_date") and week_start <= t["due_date"] <= today],
        key=lambda t: (t["due_date"], t["priority"]),
    )
    completed = [
        t for t in tasks if t["done"] and date_tag(t.get("completed_at")) >= week_start
    ]
    total = len(open_tasks) + len(completed)
    return WeeklyReview(
        week_start=week_start,
        today=today,
        carry_over=[TaskOut(**t) for t in carry_over],
        this_week=[TaskOut(**t) for t in this_week],
        completed=[TaskOut(**t) for t in completed],
        stats={
            "carry_over": len(carry_over),
            "this_week": len(this_week),
            "completed": len(completed),
            "completion_rate": round(len(completed) / total, 2) if total else 0.0,
        },
    )


@router.post("/{task_id}/focus", response_model=TaskOut)
def log_focus(task_id: str, body: FocusIn, request: Request) -> TaskOut:
    """#280: add real minutes to a task's spent_min.

    Additive rather than a set: a task worked in three sittings accumulates,
    and the focus log is the only honest record of time actually spent. The
    day-load meter (#32) reads this column.
    """
    st = request.app.state.st
    task = st.db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    updated = st.db.update_task(task_id, {"spent_min": (task.get("spent_min") or 0) + body.minutes})
    assert updated is not None
    st.bus.publish("task.updated", updated)
    return TaskOut(**updated)


@router.get("/plan", response_model=WeekPlan)
def get_week_plan(request: Request) -> WeekPlan:
    """#284/#442: distribute open work across the week and gauge its load."""
    st = request.app.state.st
    from ..db import datetime_now_local

    result = plan_week(
        st.db.list_tasks(status="open", limit=1000),
        now=datetime_now_local(),
        capacity_min=st.cfg.tasks.daily_capacity_min,
        holidays=calendar_svc.current_holidays(),
    )
    return WeekPlan(**result)


@router.get("/repos")
def get_task_repos(request: Request) -> list[dict]:
    st = request.app.state.st
    db_repos = st.db.task_repos()
    merged: dict[str, dict] = {}

    for r in db_repos:
        name = str(r.get("name") or r.get("repo") or "").strip().lower()
        if not name:
            continue
        count = int(r.get("task_count") or r.get("count") or 0)
        merged[name] = {
            "name": name,
            "path": None,
            "task_count": count,
            "count": count,
        }

    watch_dirs = getattr(st.cfg.activity, "watch_dirs", None)
    local_repos = discover_git_repos(watch_dirs)
    for lr in local_repos:
        name = str(lr.get("name") or "").strip().lower()
        if not name:
            continue
        path = str(lr["path"])
        if name in merged:
            merged[name]["path"] = path
        else:
            merged[name] = {
                "name": name,
                "path": path,
                "task_count": 0,
                "count": 0,
            }

    result = list(merged.values())
    result.sort(key=lambda r: r["name"])
    return result


@router.get("/stats")
def get_task_stats(request: Request) -> dict:
    st = request.app.state.st
    return st.db.task_stats()


@router.get("/estimate-accuracy")
def get_estimate_accuracy(request: Request) -> dict:
    """#170 time-estimate accuracy: predicted vs. actual focus time."""
    from ..services.estimate_accuracy import calculate_estimate_accuracy

    return calculate_estimate_accuracy(request.app.state.st.db)


@router.get("/funnel")
def get_task_funnel_endpoint(
    request: Request,
    days: int | None = Query(None, description="Window in days (e.g. 7, 30) or all time"),
) -> dict:
    """#250 task funnel: captured, planned, started, completed."""
    from ..services.task_funnel import get_task_funnel

    return get_task_funnel(request.app.state.st.db, days=days)


@router.get("/burndown")
def get_task_burndown_endpoint(
    request: Request,
    days: int = Query(30, ge=3, le=180, description="Window in days (3-180)"),
) -> dict:
    """#423 backlog burndown chart for unprocessed items and open tasks."""
    from ..services.burndown import get_backlog_burndown

    return get_backlog_burndown(request.app.state.st.db, days=days)



@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, request: Request) -> TaskOut:
    st = request.app.state.st
    task = st.db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return TaskOut(**task)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, body: TaskUpdateIn, request: Request) -> TaskOut:
    st = request.app.state.st
    task = st.db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return TaskOut(**task)

    # #31: touching the priority by hand marks it manual, which no later
    # inference is allowed to overwrite. Sending priority_source explicitly
    # wins (the caller is a migration or the inference path itself).
    if "priority" in changes and "priority_source" not in changes:
        changes["priority_source"] = "manual"

    try:
        updated = st.db.update_task(task_id, changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.updated", updated)
    _spawn_recurrence_if_due(st, task, updated)
    _sync_vault_and_notify_note(st, updated["note_id"])
    return TaskOut(**updated)


def _spawn_recurrence_if_due(st: Any, previous: dict, updated: dict) -> None:
    """#28: completing a recurring task schedules its next occurrence.

    `previous` is the pre-toggle snapshot; the spawn only fires on a real
    open→done transition, never on un-completing or a no-op PATCH.
    """
    if previous.get("done") or not updated.get("done") or not updated.get("recurrence"):
        return
    spawned = st.db.spawn_next_occurrence(updated["id"])
    if spawned:
        st.bus.publish("task.created", spawned)


@router.post("/{task_id}/toggle", response_model=TaskOut)
def toggle_task(task_id: str, request: Request) -> TaskOut:
    st = request.app.state.st
    task = st.db.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    updated = st.db.toggle_task(task_id)
    if not updated:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.updated", updated)
    _spawn_recurrence_if_due(st, task, updated)
    _sync_vault_and_notify_note(st, updated["note_id"])
    return TaskOut(**updated)


@router.delete("/{task_id}")
def delete_task(task_id: str, request: Request) -> dict:
    st = request.app.state.st
    task = st.db.delete_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.deleted", {"id": task_id, "note_id": task["note_id"]})
    _sync_vault_and_notify_note(st, task["note_id"])
    return {"ok": True, "id": task_id}
