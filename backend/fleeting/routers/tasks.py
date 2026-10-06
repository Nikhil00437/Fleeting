"""Dedicated Task REST API endpoints with atomic CRUD, toggle, and SSE events."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import QuickAddIn, QuickAddOut, QuickAddParseView, TaskCreateIn, TaskOut, TaskUpdateIn
from ..services import markdown
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
        limit=limit,
        offset=offset,
    )
    return [TaskOut(**t) for t in tasks]


@router.post("", response_model=TaskOut)
@router.post("/", response_model=TaskOut, include_in_schema=False)
def create_task(body: TaskCreateIn, request: Request) -> TaskOut:
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
    return TaskOut(**task)


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

    try:
        updated = st.db.update_task(task_id, changes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not updated:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.updated", updated)
    _sync_vault_and_notify_note(st, updated["note_id"])
    return TaskOut(**updated)


@router.post("/{task_id}/toggle", response_model=TaskOut)
def toggle_task(task_id: str, request: Request) -> TaskOut:
    st = request.app.state.st
    task = st.db.toggle_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.updated", task)
    _sync_vault_and_notify_note(st, task["note_id"])
    return TaskOut(**task)


@router.delete("/{task_id}")
def delete_task(task_id: str, request: Request) -> dict:
    st = request.app.state.st
    task = st.db.delete_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    st.bus.publish("task.deleted", {"id": task_id, "note_id": task["note_id"]})
    _sync_vault_and_notify_note(st, task["note_id"])
    return {"ok": True, "id": task_id}
