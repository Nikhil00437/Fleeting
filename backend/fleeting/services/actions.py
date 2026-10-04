"""Action Dispatcher Service & Core In-App Tools.

Executes user actions (task management, note management, daily digest generation,
activity tracking control) directly against SQLite and publishes live SSE events
to the frontend via EventBus.
"""

from __future__ import annotations

import inspect
from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Callable

from ..config import AUDIO_DIR, Config, ensure_dirs
from ..db import Database
from ..events import EventBus
from . import dailylog, markdown

log = logging.getLogger("fleeting.actions")


def _sync_vault_and_notify_note(
    note_id: str | None,
    db: Database,
    cfg: Config,
    bus: EventBus,
) -> None:
    """Sync parent note markdown vault file and notify UI subscribers."""
    if not note_id:
        return
    note = db.get_note(note_id)
    if not note:
        return
    if note.get("status") == "done":
        try:
            markdown.sync_note(cfg.paths, note)
        except Exception:
            log.warning("failed to sync note %s to vault", note_id, exc_info=True)
    bus.publish("note.updated", note)


def delete_tasks(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Delete all tasks matching filters or specific task IDs."""
    all_tasks = bool(params.get("all", False))
    task_ids = params.get("ids") or []
    if isinstance(task_ids, str):
        task_ids = [task_ids]
    if not task_ids and ("task_id" in params or "id" in params):
        single_id = params.get("task_id") or params.get("id")
        if single_id:
            task_ids = [str(single_id)]

    tasks_to_delete: list[dict] = []
    if all_tasks:
        status_filter = params.get("status") or "all"
        repo_filter = params.get("repo")
        tasks_to_delete = db.list_tasks(status=status_filter, repo=repo_filter, limit=100_000)
    elif task_ids:
        for tid in task_ids:
            t = db.get_task(str(tid))
            if t:
                tasks_to_delete.append(t)
    else:
        return {"ok": False, "error": "either 'all': true or 'ids' must be provided"}

    deleted_ids = []
    affected_note_ids = {t["note_id"] for t in tasks_to_delete if t.get("note_id")}
    for task in tasks_to_delete:
        tid = task["id"]
        note_id = task["note_id"]
        db.delete_task(tid)
        deleted_ids.append(tid)
        bus.publish("task.deleted", {"id": tid, "note_id": note_id})

    for nid in affected_note_ids:
        _sync_vault_and_notify_note(nid, db, cfg, bus)

    return {"ok": True, "count": len(deleted_ids), "deleted_ids": deleted_ids}


def create_task(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Create a new task."""
    text = str(params.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "task text cannot be empty"}

    note_id = params.get("note_id")
    if note_id and not db.get_note(note_id):
        return {"ok": False, "error": f"note {note_id} not found"}

    task_payload = {
        "text": text,
        "priority": params.get("priority", "P2"),
        "due_date": params.get("due_date"),
        "repo": params.get("repo"),
        "note_id": note_id,
    }
    task = db.insert_task(task_payload)
    bus.publish("task.created", task)
    _sync_vault_and_notify_note(task["note_id"], db, cfg, bus)
    return {"ok": True, "task": task}


def toggle_task(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Toggle task completion status."""
    task_id = params.get("task_id") or params.get("id")
    if not task_id:
        return {"ok": False, "error": "task_id is required"}

    task = db.toggle_task(str(task_id))
    if not task:
        return {"ok": False, "error": f"task {task_id} not found"}

    bus.publish("task.updated", task)
    _sync_vault_and_notify_note(task["note_id"], db, cfg, bus)
    return {"ok": True, "task": task}


def update_task(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Update task fields (text, priority, due_date, repo, done)."""
    task_id = params.get("task_id") or params.get("id")
    if not task_id:
        return {"ok": False, "error": "task_id is required"}

    changes = {
        k: v
        for k, v in params.items()
        if k not in ("task_id", "id") and v is not None
    }
    task = db.update_task(str(task_id), changes)
    if not task:
        return {"ok": False, "error": f"task {task_id} not found"}

    bus.publish("task.updated", task)
    _sync_vault_and_notify_note(task["note_id"], db, cfg, bus)
    return {"ok": True, "task": task}


def create_note(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Create a new note, sync to markdown vault, and publish note.created."""
    raw_text = params.get("content") or params.get("raw_text") or params.get("text") or ""
    title = str(params.get("title") or "").strip()
    tags = params.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip().lstrip("#") for t in tags.split(",") if t.strip().lstrip("#")]
    elif not isinstance(tags, list):
        tags = list(tags)
    tags = [str(t).strip().lstrip("#") for t in tags if str(t).strip().lstrip("#")]
    status = params.get("status") or "done"
    note_type = params.get("type") or "text"

    note_data = {
        "title": title or "Untitled Note",
        "raw_text": raw_text,
        "tags": tags,
        "status": status,
        "type": note_type,
        "summary": params.get("summary") or "",
        "action_items": params.get("action_items") or [],
        "source": params.get("source") or {},
    }
    note = db.insert_note(note_data)
    if note.get("status") == "done":
        try:
            markdown.sync_note(cfg.paths, note)
        except Exception:
            log.warning("failed to sync note %s to vault", note["id"], exc_info=True)

    bus.publish("note.created", note)
    return {"ok": True, "note": note}


def cfg_audio_dir() -> Path:
    """Where voice memos live; used to clean up files on delete."""
    ensure_dirs()
    return AUDIO_DIR


def delete_note(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Delete a note and associated tasks, removing from vault mirror."""
    note_id = params.get("note_id") or params.get("id")
    if not note_id:
        return {"ok": False, "error": "note_id is required"}

    str_note_id = str(note_id)
    task_rows = db.execute("SELECT id FROM tasks WHERE note_id = ?", (str_note_id,)).fetchall()
    note = db.delete_note(str_note_id, audio_root=cfg_audio_dir())
    if not note:
        return {"ok": False, "error": f"note {str_note_id} not found"}

    try:
        markdown.remove_note(cfg.paths, note)
    except Exception:
        log.warning("failed to remove note %s from vault", str_note_id, exc_info=True)

    for trow in task_rows:
        bus.publish("task.deleted", {"id": trow["id"], "note_id": str_note_id})

    bus.publish("note.deleted", {"id": str_note_id})
    return {"ok": True, "id": str_note_id}


def pin_note(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Pin or unpin a note."""
    note_id = params.get("note_id") or params.get("id")
    if not note_id:
        return {"ok": False, "error": "note_id is required"}

    str_note_id = str(note_id)
    note = db.get_note(str_note_id)
    if not note:
        return {"ok": False, "error": f"note {str_note_id} not found"}

    pinned = bool(params["pinned"]) if ("pinned" in params and params["pinned"] is not None) else not note.get("pinned", False)
    updated = db.update_note(str_note_id, {"pinned": pinned})
    bus.publish("note.updated", updated)
    return {"ok": True, "note": updated}


async def generate_daily_digest(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Generate or regenerate daily activity digest."""
    day = params.get("day") or datetime.now().astimezone().strftime("%Y-%m-%d")
    rolling = bool(params.get("rolling", True))

    try:
        row = await dailylog.generate_daily_log(db, cfg, day, rolling=rolling)
    except Exception as exc:
        log.exception("daily digest generation failed: %s", exc)
        return {"ok": False, "error": str(exc), "day": day}

    today_str = datetime.now().astimezone().strftime("%Y-%m-%d")
    if rolling and day == today_str:
        from ..activity import app_blocked
        sessions = [
            s for s in db.activity_sessions(day)
            if not app_blocked(cfg.activity, db, s["app_class"])
        ]
        today_seconds = sum(int(s.get("seconds", 0)) for s in sessions)
        db.kv_set(f"digest_screentime_hours_{day}", str(today_seconds // 3600))

    bus.publish("dailylog.updated", {"day": day, "kind": "daily-report" if rolling else "day-log"})
    return {"ok": True, "day": day, "row": row}


def pause_activity(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Pause or resume window activity tracking."""
    paused = bool(params.get("paused", True))
    db.kv_set("activity_paused", "1" if paused else "0")
    bus.publish("activity.live", {"paused": paused, "session": None})
    return {"ok": True, "paused": paused}


ACTIONS: dict[str, Callable[[dict, Database, Config, EventBus], Any]] = {
    "delete_tasks": delete_tasks,
    "create_task": create_task,
    "toggle_task": toggle_task,
    "update_task": update_task,
    "create_note": create_note,
    "delete_note": delete_note,
    "pin_note": pin_note,
    "generate_daily_digest": generate_daily_digest,
    "pause_activity": pause_activity,
}

AVAILABLE_ACTIONS: list[dict] = [
    {
        "name": "delete_tasks",
        "description": "Delete tasks matching filter or specific IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "all": {"type": "boolean", "description": "If true, delete all tasks matching filters."},
                "ids": {"type": "array", "items": {"type": "string"}, "description": "Specific task IDs to delete."},
                "status": {"type": "string", "enum": ["open", "done", "all"], "description": "Status filter."},
                "repo": {"type": "string", "description": "Repository filter."},
            },
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Task description text."},
                "priority": {"type": "string", "enum": ["P1", "P2", "P3"], "description": "Priority level."},
                "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format."},
                "repo": {"type": "string", "description": "Associated repository name."},
                "note_id": {"type": "string", "description": "Parent note ID."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "toggle_task",
        "description": "Toggle task completion status.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to toggle."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "update_task",
        "description": "Update task fields like text, priority, due date, repo, or status.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "ID of the task to update."},
                "text": {"type": "string", "description": "Updated text."},
                "priority": {"type": "string", "enum": ["P1", "P2", "P3"], "description": "Updated priority."},
                "due_date": {"type": "string", "description": "Updated due date YYYY-MM-DD."},
                "repo": {"type": "string", "description": "Updated repository."},
                "done": {"type": "boolean", "description": "Completion status."},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_note",
        "description": "Create a new note.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Note content / markdown text."},
                "title": {"type": "string", "description": "Note title."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "List of tags."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "delete_note",
        "description": "Delete a note by ID and remove associated tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "ID of note to delete."},
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "pin_note",
        "description": "Pin or unpin a note.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "ID of note to pin/unpin."},
                "pinned": {"type": "boolean", "description": "Pin status."},
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "generate_daily_digest",
        "description": "Generate or regenerate daily activity digest.",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Day in YYYY-MM-DD format (defaults to today)."},
                "rolling": {"type": "boolean", "description": "Whether to generate rolling 24h report."},
            },
        },
    },
    {
        "name": "pause_activity",
        "description": "Pause or resume window activity tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "paused": {"type": "boolean", "description": "True to pause, False to resume."},
            },
            "required": ["paused"],
        },
    },
]


# Tools that destroy user data. The model may request them, but they never run
# on the model's say-so alone: note content can carry injected instructions, so
# the caller must echo confirm=true after the user agrees.
DESTRUCTIVE_ACTIONS = frozenset({"delete_tasks", "delete_note"})


def _describe_destructive(tool: str, params: dict, db: Database) -> str:
    """One-line human summary of what a pending destructive action would do."""
    if tool == "delete_tasks":
        if params.get("all"):
            status = params.get("status") or "all"
            return "Delete every task" if status == "all" else f"Delete all {status} tasks"
        ids = params.get("ids") or []
        if isinstance(ids, str):
            ids = [ids]
        return f"Delete {len(ids)} task(s)" if ids else "Delete tasks"
    if tool == "delete_note":
        note_id = params.get("note_id") or params.get("id")
        note = db.get_note(str(note_id)) if note_id else None
        title = (note or {}).get("title") or ""
        return f"Delete note '{title}'" if title else f"Delete note {note_id}"
    return tool


async def execute_action(
    tool: str,
    params: dict,
    db: Database,
    cfg: Config,
    bus: EventBus,
) -> dict:
    """Execute in-app action by name, modifying DB and publishing SSE events.

    Async so an action that awaits (currently only generate_daily_digest) runs on
    the caller's event loop. Running it in a worker thread and blocking on the
    result froze SSE delivery and every other request for the length of the LLM
    call, which llm.timeout_secs allows up to 120s.
    """
    fn = ACTIONS.get(tool)
    if not fn:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    params = params or {}

    if tool in DESTRUCTIVE_ACTIONS and not params.get("confirm"):
        return {
            "ok": False,
            "error": f"'{tool}' requires confirmation",
            "needs_confirmation": {
                "tool": tool,
                "params": {k: v for k, v in params.items() if k != "confirm"},
                "summary": _describe_destructive(tool, params, db),
            },
        }

    try:
        result = fn(params, db, cfg, bus)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as exc:
        log.exception("Action %s execution failed: %s", tool, exc)
        return {"ok": False, "error": str(exc)}
