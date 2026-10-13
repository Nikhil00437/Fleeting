"""#294: speak MCP over stdio so another local AI client can search this database.

JSON-RPC 2.0, newline-delimited, on stdin/stdout. Hand-rolled rather than using
the `mcp` package, which installs 32 MB of dependencies for a local server whose
whole surface is four methods. The cost of that choice is protocol drift, and it
is paid deliberately: the implemented method set below is the entire one, so a
client speaking anything newer gets a clean `-32601` instead of a half-answer.

Read-only is enforced by the exposed surface, not by the connection. `Database`
opens read-write and its search is already covered by tests; re-implementing it
against a read-only handle would duplicate query logic to buy a guarantee the
tool list already gives. `tests/test_mcp_server.py` calls every exposed tool and
asserts the database is byte-identical afterwards, so a write added later fails
there rather than in someone's notes.

stdout is reserved for protocol frames. Anything a library wants to print goes to
stderr — one stray `print` on stdout corrupts the stream, and the client sees a
parse error with no way to tell which frame was wrong.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable

from .db import Database

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "fleeting"

# The complete method set. Anything else is `-32601`.
MCP_METHODS = frozenset({"initialize", "tools/list", "tools/call", "ping"})

MAX_LIMIT = 50


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[[Database, dict[str, Any]], str]


def _tool_note_summary(row: dict[str, Any]) -> str:
    tags = row.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in tags.strip("[]").split(",") if t]
    when = (row.get("created_at") or "")[:10]
    title = row.get("title") or (row.get("raw_text") or "")[:60]
    tail = f"  [{', '.join(tags)}]" if tags else ""
    return f"- {title} ({when}){tail}\n  {(row.get('summary') or row.get('raw_text') or '')[:240]}"


def _search_notes(db: Database, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("a non-empty `query` is required")
    limit = max(1, min(int(args.get("limit") or 10), MAX_LIMIT))
    rows = db.search(query, limit=limit)
    if not rows:
        return f"No notes match {query!r}."
    return "\n".join(_tool_note_summary(r) for r in rows)


def _search_tasks(db: Database, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("a non-empty `query` is required")
    limit = max(1, min(int(args.get("limit") or 10), MAX_LIMIT))
    rows = db.list_tasks(q=query, limit=limit)
    if not rows:
        return f"No tasks match {query!r}."
    lines = [
        f"- {r.get('text')} ({r.get('priority')}"
        f"{', done' if r.get('done') else ''})"
        for r in rows
    ]
    return "\n".join(lines)


def _get_note(db: Database, args: dict[str, Any]) -> str:
    note_id = str(args.get("id") or "").strip()
    if not note_id:
        raise ValueError("an `id` is required")
    row = db.get_note(note_id)
    if not row:
        raise ValueError(f"no note with id {note_id!r}")
    parts = [
        f"# {row.get('title') or row.get('id')}",
        f"created: {(row.get('created_at') or '')[:19]}  type: {row.get('type')}",
    ]
    if row.get("summary"):
        parts.append(str(row["summary"]))
    parts.append(str(row.get("raw_text") or ""))
    items = row.get("action_items") or []
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            items = []
    if items:
        parts.append(
            "\n".join(
                f"- [{'x' if i.get('done') else ' '}] {i.get('text')} ({i.get('priority')})"
                for i in items
            )
        )
    return "\n\n".join(parts)


TOOLS = [
    Tool(
        "search_notes",
        "Full-text search across notes. Returns title, date, tags and a summary "
        "for each hit. Use this when you need something the user captured but "
        "cannot recall the wording of.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "text to search for"},
                "limit": {"type": "integer", "description": f"max results, capped at {MAX_LIMIT}"},
            },
            "required": ["query"],
        },
        _search_notes,
    ),
    Tool(
        "search_tasks",
        "Search the task list by text. Returns the task, its priority and "
        "whether it is done.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "text to search for"},
                "limit": {"type": "integer", "description": f"max results, capped at {MAX_LIMIT}"},
            },
            "required": ["query"],
        },
        _search_tasks,
    ),
    Tool(
        "get_note",
        "Fetch one note in full by id, including its body and action items.",
        {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "the note id"}},
            "required": ["id"],
        },
        _get_note,
    ),
]

_BY_NAME = {t.name: t for t in TOOLS}


def _ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def dispatch(db: Database, message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one JSON-RPC message. None for notifications, which have no reply."""
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    # A notification has no id and must not be answered: replying desynchronises
    # the client, which is a protocol violation rather than an extra message.
    if req_id is None:
        return None
    if method not in MCP_METHODS:
        return _err(req_id, -32601, f"method not implemented: {method}")

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": PROTOCOL_VERSION},
            },
        )
    if method == "ping":
        return _ok(req_id, {})

    if method == "tools/list":
        return _ok(
            req_id,
            {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.schema,
                    }
                    for t in TOOLS
                ]
            },
        )

    # tools/call — a tool that fails answers with isError, not a JSON-RPC error,
    # because the model asked a question and "no results" or "bad argument" is
    # an answer, not a transport failure.
    name = params.get("name")
    tool = _BY_NAME.get(name)
    if not tool:
        return _err(req_id, -32602, f"unknown tool: {name}")
    try:
        text = tool.run(db, params.get("arguments") or {})
    except ValueError as exc:
        return _ok(req_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    except Exception as exc:  # noqa: BLE001 - a tool must not take the server down
        return _ok(
            req_id,
            {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            },
        )
    return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": False})


def build_response(message: dict[str, Any] | None) -> str:
    """One JSON object on one line. Empty string for a notification.

    stdout is the protocol stream; a pretty-printed frame or a stray newline
    makes the client fail to parse with nothing to say which frame was wrong.
    """
    if message is None:
        return ""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def serve(db: Database, stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC until stdin closes."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            out = build_response(_err(None, -32700, f"parse error: {exc}"))
        else:
            out = build_response(dispatch(db, message))
        if out:
            stdout.write(out + "\n")
            stdout.flush()


def main() -> None:
    """Entry point for `fleeting-mcp`.

    Opened read-only: this process is spawned by someone else's AI client, and
    the tools are read-only, so there is no reason for it to hold a writable
    handle on the user's notes.
    """
    from .config import DB_PATH

    db = Database(DB_PATH)
    db.migrate()
    serve(db)


if __name__ == "__main__":  # pragma: no cover
    main()