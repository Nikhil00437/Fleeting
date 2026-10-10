"""Action Dispatcher Service & Core In-App Tools.

Executes user actions (task management, note management, daily digest generation,
activity tracking control) directly against SQLite and publishes live SSE events
to the frontend via EventBus.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import time
from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Callable

from .. import config as _config
from ..config import Config, ensure_dirs
from ..db import Database, new_id
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
        tasks_to_delete = db.list_tasks(status=status_filter, repo=repo_filter, list="all", limit=100_000)
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
    """Where voice memos live; used to clean up files on delete.

    Read from the config module rather than bound at import: a module-level
    `from ..config import AUDIO_DIR` snapshot cannot be redirected, which is
    how test stubs ended up in the user's real audio directory.
    """
    ensure_dirs()
    return _config.AUDIO_DIR


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


# ---- #109 bulk edits ------------------------------------------------------
#
# "Retag all my router notes as homelab" touches every note that matched a
# phrase the user never saw until after it was written. So this is two calls:
# the first resolves and shows, the second writes. Nothing in between can
# retag a note on its own.
#
# Selection is lexical FTS through the one query parser rather than the hybrid
# path: a bulk edit must not need the embedding server, must not depend on
# vectors that change when the model changes, and must produce the same set
# twice for the same words.

BULK_OPERATIONS = ("add_tag", "remove_tag", "archive", "unarchive", "pin", "unpin")

# The keyword search's own maximum, so "hit the cap" and "too many to touch"
# are the same condition rather than two numbers that can disagree.
BULK_CAP = 200

# A preview is a promise about a moment; fifteen minutes is long enough to read
# a list and decide, short enough that a tab left open overnight cannot apply a
# stale selection in the morning.
BULK_PREVIEW_TTL = 900


def _bulk_find(query: str, cfg: Config, db: Database) -> list[dict]:
    from .semantic_search import hybrid_search

    return hybrid_search(db, query, cfg, mode="keyword", limit=BULK_CAP)


def _bulk_matching_ids(query: str, cfg: Config, db: Database) -> list[str]:
    """The notes a query selects, refusing anything broader than BULK_CAP."""
    if not query or not query.strip():
        raise ValueError("bulk_edit needs a query saying which notes")
    notes = _bulk_find(query, cfg, db)
    if len(notes) >= BULK_CAP:
        # Never truncate: silently editing the first 200 of 5000 is worse than
        # refusing, because the user cannot see what was left out.
        raise ValueError(
            f"At least {BULK_CAP} notes match '{query}'. Narrow it with "
            f"tag:, type:, person: or a date so the edit stays reviewable."
        )
    return [str(n["id"]) for n in notes]


def _bulk_preview_key(query: str, operation: str, value: str) -> str:
    """The storage key for one preview, derived from what it would change.

    Deliberately not random. The confirm flow re-sends the *original prompt*
    and lets the model call the tool again, so a random token would never come
    back and the edit would loop on the preview forever. Keying by the edit
    itself means the confirm turn finds exactly the preview it was shown —
    and if the model comes back with different parameters, that is a
    different key, so it previews again instead of applying something the
    user never saw.
    """
    digest = hashlib.sha256(f"{query.strip()}|{operation}|{value}".encode()).hexdigest()
    return f"bulk_preview:{digest[:32]}"


def _bulk_store_preview(
    db: Database, key: str, ids: list[str], operation: str, value: str
) -> str:
    db.kv_set(
        key,
        json.dumps({"ids": ids, "operation": operation, "value": value, "at": time.time()}),
    )
    return key.split(":", 1)[1]


def _bulk_read_preview(params: dict, db: Database, *, spend: bool = True) -> dict:
    """Fetch a preview record, optionally spending it.

    `execute_action` snapshots the undo state *before* the action runs, so the
    snapshot peeks (`spend=False`) and the action spends. A preview that could
    be applied twice is the one thing this whole tool exists to prevent.
    """
    token = str(params.get("preview_token") or "").strip()
    if not token:
        raise ValueError("bulk_edit needs a preview_token")
    key = f"bulk_preview:{token}"
    raw = db.kv_get(key)
    if not raw:
        raise ValueError("That preview has expired. Run it again to see the notes.")
    if spend:
        db.kv_delete(key)
    rec = json.loads(raw)
    if time.time() - float(rec.get("at") or 0) > BULK_PREVIEW_TTL:
        if spend:
            db.kv_delete(key)
        raise ValueError("That preview has expired. Run it again to see the notes.")
    return rec


def _bulk_confirmed_token(params: dict, db: Database) -> str | None:
    """The preview token this call is approving, if it is approving one.

    The confirm turn re-sends the prompt rather than the tool call, so the
    token is looked up from the edit's own key. An edit with no stored preview
    has not been shown to the user, so it returns None and previews instead —
    applying on a bare confirm=true would be the one way to write notes the
    user never saw.
    """
    if params.get("preview_token") or not params.get("confirm"):
        return None
    operation = str(params.get("operation") or "").strip()
    if not operation:
        return None
    query = str(params.get("query") or "")
    value = str(params.get("value") or "").strip().lstrip("#").lower()
    key = _bulk_preview_key(query, operation, value)
    return key.split(":", 1)[1] if db.kv_get(key) else None


def bulk_edit(params: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Preview first, then apply, to every note in the preview.

    Both phases go through one entry point so the operation can never be
    applied from the preview call: without a token this only reports.
    """
    params = params or {}
    operation = str(params.get("operation") or "").strip()
    value = str(params.get("value") or "").strip().lstrip("#").lower()
    query = str(params.get("query") or "")
    confirmed = _bulk_confirmed_token(params, db)
    if confirmed:
        params = {**params, "preview_token": confirmed}
    applying = bool(params.get("preview_token"))

    try:
        if applying:
            # The operation and tag come from the preview, not from this call:
            # the user approved a specific change to a specific set, so a
            # re-specified query or value here must not widen or redirect it.
            rec = _bulk_read_preview(params, db)
            ids = rec["ids"]
            operation = str(rec.get("operation") or "")
            value = str(rec.get("value") or "")
        else:
            if operation not in BULK_OPERATIONS:
                raise ValueError(
                    f"Unknown operation '{operation}'. "
                    f"Use one of: {', '.join(BULK_OPERATIONS)}"
                )
            if operation in ("add_tag", "remove_tag") and not value:
                raise ValueError(f"'{operation}' needs a tag name")
            query = str(params.get("query") or "")
            ids = _bulk_matching_ids(query, cfg, db)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if operation not in BULK_OPERATIONS:
        return {"ok": False, "error": f"Unknown operation '{operation}'."}

    if not ids:
        return {"ok": False, "error": "No notes matched."}

    notes = [n for n in (db.get_note(i) for i in ids) if n and not n.get("trashed_at")]
    matches = [{"id": n["id"], "title": n.get("title") or "(untitled)"} for n in notes]

    if not applying:
        return {
            "ok": True,
            "preview": True,
            "operation": operation,
            "value": value or None,
            "count": len(matches),
            "matches": matches,
            "preview_token": _bulk_store_preview(
                db,
                _bulk_preview_key(str(params.get("query") or ""), operation, value),
                [n["id"] for n in notes],
                operation,
                value,
            ),
        }

    from .tags_vocab import apply_preferred_tags, preferred_tags

    changed = 0
    for note in notes:
        fields: dict[str, Any] = {}
        if operation == "add_tag":
            # #257: the same snapping enrichment output gets, so a tag typed
            # here lands on the same word the model would have produced.
            tags = [str(t) for t in (note.get("tags") or [])]
            # Dedupe before snapping: apply_preferred_tags returns its input
            # untouched when no vocabulary is configured, so without this an
            # existing tag plus the same tag again compares unequal and the
            # note is rewritten with a duplicate.
            candidates = list(dict.fromkeys(tags + [value]))
            new = apply_preferred_tags(candidates, preferred_tags(cfg))
            if new != tags:
                fields["tags"] = new
        elif operation == "remove_tag":
            tags = [str(t) for t in (note.get("tags") or [])]
            if value in tags:
                fields["tags"] = [t for t in tags if t != value]
        elif operation in ("archive", "unarchive"):
            target = 1 if operation == "archive" else 0
            if int(note.get("archived") or 0) != target:
                fields["archived"] = target
        elif operation in ("pin", "unpin"):
            target = 1 if operation == "pin" else 0
            if int(note.get("pinned") or 0) != target:
                fields["pinned"] = target

        if not fields:
            continue
        updated = db.update_note(note["id"], fields)
        if updated:
            changed += 1
            # Every write the UI must see live announces itself; a bulk edit
            # that skips this leaves the view stale until navigation.
            bus.publish("note.updated", updated)

    return {
        "ok": True,
        "operation": operation,
        "value": value or None,
        "count": len(matches),
        "changed": changed,
        "matches": matches,
    }


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
    "bulk_edit": bulk_edit,
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
    {
        "name": "bulk_edit",
        "description": (
            "Change one thing across every note matching a query, e.g. 'retag all "
            "my router notes as homelab'. Never applies on the first call: it "
            "reports the matched notes and returns a preview_token, which you "
            "must pass back to apply the change."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Which notes, in plain words. Operators like tag:, "
                        "person: and type: work here too."
                    ),
                },
                "operation": {
                    "type": "string",
                    "enum": ["add_tag", "remove_tag", "archive", "unarchive", "pin", "unpin"],
                    "description": "What to change on each matched note.",
                },
                "value": {"type": "string", "description": "The tag, for add_tag and remove_tag."},
                "preview_token": {
                    "type": "string",
                    "description": (
                        "From the preview call. Applies exactly the notes that "
                        "preview listed; omit it to preview instead of editing."
                    ),
                },
            },
            "required": ["operation"],
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


def _snapshot_undo(tool: str, params: dict, db: Database) -> tuple[str, dict] | None:
    """#103: capture the prior state of whatever `tool` is about to change.

    Returns (kind, before) or None when the action is not reversible. The kinds
    are deliberately the *table rows* rather than a tool name — restoring a row
    is the same operation whatever asked for the delete.
    """
    params = params or {}
    if tool == "delete_note":
        note_id = str(params.get("note_id") or params.get("id") or "")
        note = db.get_note(note_id)
        if not note:
            return None
        tasks = [dict(r) for r in db.execute(
            "SELECT * FROM tasks WHERE note_id = ?", (note_id,)
        ).fetchall()]
        return ("note_deleted", {"note": note, "tasks": tasks})

    if tool == "delete_tasks":
        ids = params.get("ids") or []
        if isinstance(ids, str):
            ids = [ids]
        if params.get("all"):
            rows = db.list_tasks(status=params.get("status") or "all",
                                 repo=params.get("repo"), list="all", limit=100_000)
        else:
            rows = [t for t in (db.get_task(str(i)) for i in ids) if t]
        return ("tasks_deleted", {"tasks": rows}) if rows else None

    if tool == "create_task":
        return ("tasks_created", {})

    if tool == "create_note":
        return ("note_created", {})

    if tool == "toggle_task":
        task_id = str(params.get("task_id") or params.get("id") or "")
        task = db.get_task(task_id)
        return ("task_fields", {"id": task_id, "done": int(task["done"])}) if task else None

    if tool == "update_task":
        task_id = str(params.get("task_id") or params.get("id") or "")
        task = db.get_task(task_id)
        if not task:
            return None
        fields = ("text", "priority", "due_date", "repo", "completed_at", "note_id")
        return ("task_fields", {
            "id": task_id,
            **{f: task.get(f) for f in fields if f in params and params[f] is not None},
        })

    if tool == "pin_note":
        note_id = str(params.get("note_id") or params.get("id") or "")
        note = db.get_note(note_id)
        return ("note_fields", {"id": note_id, "pinned": int(note["pinned"])}) if note else None

    if tool == "pause_activity":
        return ("kv", {"key": "activity_paused", "value": db.kv_get("activity_paused", "0")})

    if tool == "bulk_edit":
        # The before-state of every note the preview named, captured before the
        # edit runs. Reading the preview here rather than trusting the model's
        # params is what keeps undo pointing at the notes that actually change.
        # The confirm turn arrives without a token, so resolve it the same way
        # the action will.
        confirmed = _bulk_confirmed_token(params, db)
        if confirmed:
            params = {**params, "preview_token": confirmed}
        try:
            rec = _bulk_read_preview(params, db, spend=False)
        except ValueError:
            rec = None
        if not rec:
            return None
        rows = []
        for note_id in rec["ids"]:
            note = db.get_note(str(note_id))
            if note:
                rows.append(
                    {
                        "id": note["id"],
                        "tags": [str(t) for t in (note.get("tags") or [])],
                        "archived": int(note.get("archived") or 0),
                        "pinned": int(note.get("pinned") or 0),
                    }
                )
        return ("bulk_edit", {"notes": rows}) if rows else None

    # generate_daily_digest is deliberately absent: the previous digest is gone
    # once regenerated, and re-deriving it would be a guess. It has its own
    # path — an edited report is preserved by #72's edited_body.
    return None


def _restore_undo(rec: dict, db: Database, cfg: Config, bus: EventBus) -> dict:
    """Put back what `_snapshot_undo` took. Raises on failure; caller catches."""
    kind = rec["kind"]
    before = rec["before"]

    if kind == "note_deleted":
        note = before["note"]
        # Re-insert with the original id and timestamps so citations, vault
        # filenames and `created_at` ordering all survive the round trip.
        # insert_note re-derives tasks from action_items, so tasks listed in
        # the note come back on their own; the rest are restored explicitly.
        db.insert_note({**note, "status": "done"})
        derived = {
            t["text"] for t in db.execute(
                "SELECT text FROM tasks WHERE note_id = ?", (note["id"],)
            ).fetchall()
        }
        for t in before["tasks"]:
            if t["text"] not in derived:
                db.insert_task({**t, "id": t["id"]})
        restored = db.get_note(note["id"])
        if restored:
            try:
                markdown.sync_note(cfg.paths, restored)
            except Exception:
                log.warning("undo could not restore vault file for %s", note["id"], exc_info=True)
        bus.publish("note.created", restored or note)

    elif kind == "tasks_deleted":
        for t in before["tasks"]:
            db.insert_task({**t, "id": t["id"]})
            bus.publish("task.created", t)

    elif kind == "tasks_created":
        # Undoing a creation means removing what was added; the snapshot only
        # records that this happened, so the ids come from the action result.
        for tid in before.get("created_ids") or []:
            task = db.get_task(tid)
            if not task:
                continue
            db.delete_task(tid)
            bus.publish("task.deleted", {"id": tid, "note_id": task["note_id"]})

    elif kind == "note_created":
        for nid in before.get("created_ids") or []:
            if db.get_note(nid):
                db.delete_note(nid)
                bus.publish("note.deleted", {"id": nid})

    elif kind in ("task_fields", "note_fields"):
        changes = {k: v for k, v in before.items() if k != "id"}
        if kind == "task_fields":
            # completed_at tracks done; restoring `done` alone leaves a done task
            # with no completion timestamp.
            if "done" in changes and "completed_at" not in changes:
                changes["completed_at"] = None if not changes["done"] else db.now_iso_local()
            task = db.update_task(before["id"], changes)
            if task:
                bus.publish("task.updated", task)
        else:
            note = db.update_note(before["id"], changes)
            if note:
                bus.publish("note.updated", note)

    elif kind == "kv":
        db.kv_set(before["key"], before["value"])
        bus.publish("activity.live", {"paused": before["value"] == "1", "session": None})

    elif kind == "bulk_edit":
        # #109: the snapshot holds every touched field of every touched note,
        # so this is one restore loop rather than one branch per operation —
        # archive, pin and retag are undone by the same code.
        for row in before["notes"]:
            note = db.update_note(
                row["id"],
                {"tags": row["tags"], "archived": row["archived"], "pinned": row["pinned"]},
            )
            if note:
                bus.publish("note.updated", note)

    else:
        return {"ok": False, "error": f"cannot undo '{kind}'"}

    return {"ok": True}


async def undo_action(token: str, db: Database, cfg: Config, bus: EventBus) -> dict:
    """#103: reverse one previously-executed assistant action.

    The token is consumed even when the restore fails, so a broken undo cannot
    be replayed into a worse state by clicking again.
    """
    rec = db.consume_undo(token)
    if not rec:
        return {"ok": False, "error": "Undo not found — it may have already been used."}
    try:
        return _restore_undo(rec, db, cfg, bus)
    except Exception as exc:
        log.exception("Undo %s failed", token)
        return {"ok": False, "error": str(exc)}


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

    On success an undoable action also returns `undo`: a single-use token the
    caller can hand back to `undo_action` (#103).
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

    snapshot = _snapshot_undo(tool, params, db)
    try:
        result = fn(params, db, cfg, bus)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        log.exception("Action %s execution failed: %s", tool, exc)
        return {"ok": False, "error": str(exc)}

    if snapshot and isinstance(result, dict) and result.get("ok"):
        token = new_id()
        kind, before = snapshot
        # For creations the snapshot is empty; the ids to remove come from what
        # the action actually made.
        if kind in ("tasks_created", "note_created"):
            row = result.get("task") or result.get("note")
            if not (row and row.get("id")):
                return result  # nothing identifiable to undo
            before = {"created_ids": [row["id"]]}
        try:
            db.record_undo(token, kind, before)
            result["undo"] = token
        except Exception as exc:
            log.warning("could not record undo for %s: %s", tool, exc)
    return result
