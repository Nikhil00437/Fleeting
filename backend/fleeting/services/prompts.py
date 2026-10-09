"""#105 saved prompts — named questions you can rerun.

Deliberately a prompt and nothing else. The idea says "recipes you can
rerun", and a prompt that grew its own execution semantics would be a second
assistant with a second confirmation story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..db import new_id, now_iso

if TYPE_CHECKING:
    from ..db import Database

# A pasted paragraph is a normal thing to paste, so the body is truncated
# rather than refused. The name is a label and stays short.
MAX_PROMPT_CHARS = 4000
MAX_NAME_CHARS = 80


def create_prompt(db: Database, name: str, body: str) -> dict:
    n, b = (name or "").strip(), (body or "").strip()
    if not n or not b:
        raise ValueError("a saved prompt needs a name and a body")
    row = {
        "id": new_id(),
        "name": n[:MAX_NAME_CHARS],
        "body": b[:MAX_PROMPT_CHARS],
        "at": now_iso(),
    }
    db.execute(
        "INSERT INTO saved_prompts (id, name, body, at) VALUES (:id, :name, :body, :at)",
        row,
    )
    db.commit()
    return row


def update_prompt(db: Database, prompt_id: str, *, name: str, body: str) -> dict | None:
    n, b = (name or "").strip(), (body or "").strip()
    if not n or not b:
        raise ValueError("a saved prompt needs a name and a body")
    cur = db.execute(
        "UPDATE saved_prompts SET name = :n, body = :b WHERE id = :id",
        {"id": prompt_id, "n": n[:MAX_NAME_CHARS], "b": b[:MAX_PROMPT_CHARS]},
    )
    db.commit()
    if cur.rowcount == 0:
        return None
    return _get(db, prompt_id)


def delete_prompt(db: Database, prompt_id: str) -> bool:
    cur = db.execute("DELETE FROM saved_prompts WHERE id = ?", (prompt_id,))
    db.commit()
    return cur.rowcount > 0


def _get(db: Database, prompt_id: str) -> dict | None:
    row = db.execute(
        "SELECT id, name, body, at FROM saved_prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    return dict(row) if row else None


def list_prompts(db: Database, *, q: str = "", limit: int = 100) -> list[dict]:
    """Newest first, searchable by name *or* body — you remember one or the other."""
    sql = "SELECT id, name, body, at FROM saved_prompts"
    params: dict = {}
    needle = (q or "").strip()
    if needle:
        sql += " WHERE name LIKE :q OR body LIKE :q"
        params["q"] = f"%{needle}%"
    sql += " ORDER BY at DESC, rowid DESC LIMIT :limit"
    params["limit"] = max(1, min(int(limit), 200))
    return [dict(r) for r in db.execute(sql, params).fetchall()]
