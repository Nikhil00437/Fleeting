"""#111 assistant conversation history: saved, searchable, pinnable.

One row per conversation, transcript as a JSON array. A local single-user
chat log stays small (hundreds of rows, not millions), so a `LIKE` scan beats
a second FTS table plus triggers and rebuild discipline. The client owns the
message list it already has and posts the whole conversation on each turn,
which keeps all of this out of the streaming path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..db import Database, now_iso

log = logging.getLogger("fleeting.chatlog")

MAX_MESSAGES = 500
TITLE_LEN = 80
PREVIEW_LEN = 200


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text[:TITLE_LEN] + "…" if len(text) > TITLE_LEN else text


def title_of(messages: list[dict[str, Any]]) -> str:
    """First user message, trimmed — good enough to recognise a thread."""
    for role in ("user", "assistant"):
        for m in messages:
            if m.get("role") == role and m.get("content"):
                return _clip(str(m["content"]))
    return "Empty conversation"


def _decode(row: dict[str, Any]) -> dict[str, Any]:
    try:
        row["messages"] = json.loads(row.get("messages") or "[]")
    except (TypeError, ValueError):
        # A truncated or hand-edited row must not 500 the whole sidebar.
        log.warning("assistant chat %s has an unreadable transcript", row.get("id"))
        row["messages"] = []
    return row


def save_chat(db: Database, chat_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Upsert one conversation. An empty transcript is ignored, not stored."""
    kept = [
        {k: m[k] for k in ("role", "content", "sources") if m.get(k) is not None}
        for m in messages[-MAX_MESSAGES:]
        if m.get("role") in {"user", "assistant"} and m.get("content")
    ]
    if not kept:
        row = db.execute("SELECT * FROM assistant_chats WHERE id = ?", (chat_id,)).fetchone()
        return _decode(dict(row)) if row else {"id": chat_id, "title": "", "messages": []}

    payload = json.dumps(kept)
    exists = db.execute("SELECT 1 FROM assistant_chats WHERE id = ?", (chat_id,)).fetchone()
    if exists:
        db.execute(
            "UPDATE assistant_chats SET messages = ?, title = ?, updated_at = ? WHERE id = ?",
            (payload, title_of(kept), now_iso(), chat_id),
        )
    else:
        db.execute(
            "INSERT INTO assistant_chats (id, title, pinned, messages, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?, ?)",
            (chat_id, title_of(kept), payload, now_iso(), now_iso()),
        )
    db.commit()
    row = db.execute("SELECT * FROM assistant_chats WHERE id = ?", (chat_id,)).fetchone()
    return _decode(dict(row))  # type: ignore[arg-type]


def list_chats(
    db: Database, *, q: str = "", limit: int = 50, pinned_only: bool = False
) -> list[dict[str, Any]]:
    """Search covers title *and* transcript; pinned threads sort first.

    A hit also carries `preview`/`hit_count` so the search box can show the
    matching line instead of the whole transcript.
    """
    where, params = ["1=1"], []
    needle = q.strip()
    if needle:
        where.append("(title LIKE ? OR messages LIKE ?)")
        params += [f"%{needle}%", f"%{needle}%"]
    if pinned_only:
        where.append("pinned = 1")
    rows = db.execute(
        "SELECT * FROM assistant_chats WHERE "
        + " AND ".join(where)
        + " ORDER BY pinned DESC, updated_at DESC LIMIT ?",
        [*params, limit],
    ).fetchall()

    out = []
    for row in rows:
        chat = _decode(dict(row))
        if needle:
            hits = [str(m.get("content", "")) for m in chat["messages"] if needle.lower() in str(m.get("content", "")).lower()]
            chat["hit_count"] = len(hits)
            chat["preview"] = _clip(hits[0])[:PREVIEW_LEN] if hits else ""
        else:
            chat["hit_count"] = 0
            chat["preview"] = ""
        out.append(chat)
    return out


def set_pinned(db: Database, chat_id: str, pinned: bool) -> dict[str, Any] | None:
    db.execute("UPDATE assistant_chats SET pinned = ? WHERE id = ?", (1 if pinned else 0, chat_id))
    db.commit()
    row = db.execute("SELECT * FROM assistant_chats WHERE id = ?", (chat_id,)).fetchone()
    return _decode(dict(row)) if row else None


def delete_chat(db: Database, chat_id: str) -> bool:
    cur = db.execute("DELETE FROM assistant_chats WHERE id = ?", (chat_id,))
    db.commit()
    return cur.rowcount > 0