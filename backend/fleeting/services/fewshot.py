"""#256: few-shot examples from enrichments the user corrected.

Feedback is only useful if something reads it. The signal that a note was
*corrected* is not the thumb alone — it is a note whose stored title and tags
differ from what the model produced. `note_versions` already records the
pre-edit title, so the comparison is free.
"""

from __future__ import annotations

import json

from ..db import Database

# A few-shot prompt that grows with the inbox is just a second inbox: the
# model pays for every token and the signal from four good examples beats the
# signal from forty diluted ones.
DEFAULT_LIMIT = 4
EXCERPT_CHARS = 400


def _was_edited(note_id: str, db: Database) -> bool:
    """True when the title on screen differs from what was first generated."""
    row = db.execute(
        "SELECT title FROM note_versions WHERE note_id = ? ORDER BY id ASC LIMIT 1",
        (note_id,),
    ).fetchone()
    if not row:
        return False
    current = db.execute("SELECT title FROM notes WHERE id = ?", (note_id,)).fetchone()
    return bool(current and current["title"] and current["title"] != row["title"])


def few_shot_examples(db: Database, *, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Corrected enrichments, most recently judged first.

    `enrich_feedback != 0` is the verdict; a differing title is the correction.
    Sensitive (#26) and trashed rows are excluded at read time — a corrected
    secret is still a secret, and a discarded idea is still discarded.
    """
    rows = db.execute(
        """
        SELECT id, title, raw_text, tags, enrich_feedback
        FROM notes
        WHERE enrich_feedback != 0
          AND sensitive = 0
          AND trashed_at IS NULL
          AND status = 'done'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit * 4,),
    ).fetchall()

    examples: list[dict] = []
    for row in rows:
        if len(examples) >= limit:
            break
        if not _was_edited(row["id"], db):
            continue
        excerpt = " ".join((row["raw_text"] or "").split())
        if not excerpt or not (row["title"] or "").strip():
            continue
        examples.append({
            "excerpt": excerpt[:EXCERPT_CHARS],
            "title": row["title"].strip(),
            # Raw SQL, so tags is still the stored JSON blob.
            "tags": [t for t in (json.loads(row["tags"] or "[]")) if t],
        })
    return examples


def build_few_shot(db: Database, *, limit: int = DEFAULT_LIMIT) -> str:
    """A prompt fragment, or "" when there is nothing worth showing."""
    examples = few_shot_examples(db, limit=limit)
    if not examples:
        return ""
    lines = ["The user corrected these past enrichments. Match their judgement:"]
    for ex in examples:
        tags = ", ".join(ex["tags"]) if ex["tags"] else "(none)"
        lines.append(f'- Note: "{ex["excerpt"]}"\n  Title: {ex["title"]}\n  Tags: {tags}')
    return "\n".join(lines)
