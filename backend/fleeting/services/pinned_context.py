"""#101 pinned context: the notes you mean, regardless of what the query matched.

Retrieval answers the question you asked. Sometimes you know which note you
mean and the ranking does not — a decision you made last month, a decision you
now need. Pinning says so explicitly, and the note goes into the context
whether or not anything matched it.

Pinned notes are labelled as pinned in the context block. That is the whole
point of the feature: the assistant can say "you pinned this" rather than
citing it as if it had been found, which is the difference between a citation
you can trust and one you cannot.

Small surface on purpose. A thread holds pinned note ids; there is no second
retrieval system and no second parser.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..db import Database

log = logging.getLogger("fleeting.pinned")

MAX_PINNED = 12


def _load(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def pinned_ids(db: "Database", chat_id: str) -> list[str]:
    row = db.execute(
        "SELECT context_ids FROM assistant_chats WHERE id = ?", (chat_id,)
    ).fetchone()
    return _load(row["context_ids"]) if row else []


def pin_note(db: "Database", chat_id: str, note_id: str) -> list[str]:
    """Attach a note to a thread. Idempotent, and capped.

    The cap is on purpose: a thread with fifty pinned notes is a thread where
    everything is context, which is the same as no pinning.
    """
    current = pinned_ids(db, chat_id)
    if note_id in current:
        return current
    if len(current) >= MAX_PINNED:
        raise ValueError(f"a thread can hold {MAX_PINNED} pinned notes")
    current.append(note_id)
    _save(db, chat_id, current)
    return current


def unpin_note(db: "Database", chat_id: str, note_id: str) -> list[str]:
    current = [n for n in pinned_ids(db, chat_id) if n != note_id]
    _save(db, chat_id, current)
    return current


def _save(db: "Database", chat_id: str, ids: list[str]) -> None:
    db.execute(
        "UPDATE assistant_chats SET context_ids = ? WHERE id = ?",
        (json.dumps(ids), chat_id),
    )
    db.commit()


def pinned_notes(db: "Database", chat_id: str) -> list[dict]:
    """The pinned notes, in the order they were pinned.

    Trashed and sensitive notes are dropped rather than sent: a note the user
    hid is not something the assistant should surface because it was pinned
    three weeks ago.
    """
    out = []
    for note_id in pinned_ids(db, chat_id):
        note = db.get_note(note_id)
        if not note or note.get("trashed_at") or note.get("sensitive"):
            continue
        out.append(note)
    return out


def pinned_block(notes: list[dict]) -> str:
    """The context section for pinned notes, labelled so the model can cite it."""
    if not notes:
        return ""
    lines = [
        "The user pinned these notes into this conversation. They chose them "
        "explicitly, so treat them as the subject even when the question does "
        "not match, and say \"you pinned this\" rather than implying they were "
        "found by search:"
    ]
    for note in notes:
        title = (note.get("title") or "(untitled)").strip()
        body = (note.get("raw_text") or "").strip()[:1200]
        lines.append(f"[pinned {note['id']}] {title}\n{body}")
    return "\n\n".join(lines)