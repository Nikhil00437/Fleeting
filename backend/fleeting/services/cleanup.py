"""Monthly cleanup assistant (#421).

Proposes low-risk, human-approved maintenance: archiving untouched notes,
tagging untagged ones, reviewing empty titles, and looking at exact-duplicate
titles. Deliberately heuristic — no embeddings, no LLM call — and every
suggestion needs an explicit apply.

Merge-duplicates (#16) stays deferred to 0.6: without tuned embeddings the
best we can do honestly is surface identical titles, not near-duplicates.
"""

from __future__ import annotations

from datetime import timedelta

from ..db import Database, now_iso

# Notes untouched for this long with nothing pending are archive candidates.
STALE_DAYS = 45


def cleanup_suggestions(db: Database, limit_per_kind: int = 25) -> list[dict]:
    cutoff = (datetime_utc() - timedelta(days=STALE_DAYS)).isoformat(timespec="seconds")
    suggestions: list[dict] = []

    # 1) Archive candidates: finished, unpinned, unstarred, no open tasks,
    #    not in any collection, and cold for STALE_DAYS.
    rows = db.execute(
        """
        SELECT n.id, n.title, n.raw_text, n.updated_at
        FROM notes n
        WHERE n.trashed_at IS NULL AND n.archived = 0 AND n.status = 'done'
          AND n.pinned = 0 AND n.starred = 0 AND n.sensitive = 0
          AND n.updated_at <= :cutoff
          AND NOT EXISTS (SELECT 1 FROM tasks t WHERE t.note_id = n.id AND t.done = 0)
          AND NOT EXISTS (SELECT 1 FROM collection_items ci WHERE ci.note_id = n.id)
        ORDER BY n.updated_at ASC
        LIMIT :limit
        """,
        {"cutoff": cutoff, "limit": limit_per_kind},
    ).fetchall()
    for r in rows:
        title = r["title"] or (r["raw_text"] or "")[:60]
        suggestions.append({
            "kind": "archive",
            "note_id": r["id"],
            "title": title,
            "reason": f"untouched for over {STALE_DAYS} days with no open tasks",
        })

    # 2) Untagged notes: a type-based tag is a reasonable starting point.
    rows = db.execute(
        """
        SELECT id, title, raw_text, type FROM notes
        WHERE trashed_at IS NULL AND archived = 0 AND tags = '[]'
        ORDER BY created_at DESC LIMIT :limit
        """,
        {"limit": limit_per_kind},
    ).fetchall()
    for r in rows:
        suggestions.append({
            "kind": "add_tag",
            "note_id": r["id"],
            "title": r["title"] or (r["raw_text"] or "")[:60],
            "value": r["type"],
            "reason": f"no tags yet — suggest #{r['type']}",
        })

    # 3) Empty titles: enrichment missed or the note predates it.
    rows = db.execute(
        """
        SELECT id, raw_text FROM notes
        WHERE trashed_at IS NULL AND archived = 0 AND title = ''
        ORDER BY created_at DESC LIMIT :limit
        """,
        {"limit": limit_per_kind},
    ).fetchall()
    for r in rows:
        suggestions.append({
            "kind": "rename",
            "note_id": r["id"],
            "title": (r["raw_text"] or "")[:60],
            "reason": "no title — open it and name it",
        })

    # 4) Exact-duplicate titles: merge candidates for a human call.
    rows = db.execute(
        """
        SELECT lower(title) AS key, COUNT(*) AS c
        FROM notes
        WHERE trashed_at IS NULL AND archived = 0 AND title != ''
        GROUP BY key HAVING c > 1
        ORDER BY c DESC LIMIT :limit
        """,
        {"limit": limit_per_kind},
    ).fetchall()
    for r in rows:
        ids = [
            row["id"]
            for row in db.execute(
                "SELECT id FROM notes WHERE trashed_at IS NULL AND archived = 0 "
                "AND lower(title) = :key ORDER BY created_at ASC",
                {"key": r["key"]},
            ).fetchall()
        ]
        titles = db.execute(
            "SELECT title FROM notes WHERE id = ?", (ids[0],)
        ).fetchone()
        suggestions.append({
            "kind": "merge",
            "note_id": ids[0],
            "extra_note_ids": ids[1:],
            "title": titles["title"] if titles else r["key"],
            "reason": f"{r['c']} notes share this title — review for duplicates",
        })

    return suggestions


def datetime_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
