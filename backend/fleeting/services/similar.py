"""Related-notes queries (#320 find similar, #23 drawer suggestions).

The neighbour query is pure cosine over the stored embedding corpus —
embeddings exist for every processed note (pipeline + backfill keep them
fresh), so no new index is needed. A note without a stored embedding gets a
query-time vector from the same text builder embed_note uses, so the two
shapes stay comparable.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from .embeddings import cosine_similarity, embed_text, embedding_text_for, unpack_vector

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.similar")


def find_similar(
    db: Database,
    cfg: Config,
    note_id: str,
    *,
    limit: int = 8,
    threshold: float = 0.05,
) -> list[dict]:
    """Notes most similar to the given one, best first.

    Returns note dicts with `score` (cosine similarity) and
    `match_type='similar'`. Self, trashed and archived notes are excluded.
    """
    note = db.get_note(note_id)
    if not note:
        return []

    stored = db.get_note_embedding(note_id)
    if stored:
        try:
            query_vec = unpack_vector(stored["embedding"])
        except Exception:
            query_vec = None
    else:
        query_vec = None

    if query_vec is None:
        text = embedding_text_for(note)
        if not text:
            return []
        query_vec = embed_text(text, cfg)

    clamped_limit = min(max(1, int(limit)), 50)
    results: list[dict] = []
    for row in db.get_all_embeddings():
        other_id = str(row["note_id"])
        if other_id == note_id:
            continue
        try:
            vec = unpack_vector(row["embedding"])
        except Exception:
            continue
        sim = cosine_similarity(query_vec, vec)
        if sim <= threshold:
            continue
        other = db.get_note(other_id)
        if not other or other.get("archived") or other.get("trashed_at"):
            continue
        other["score"] = float(round(sim, 4))
        other["match_type"] = "similar"
        results.append(other)
        if len(results) >= clamped_limit * 4:
            break

    results.sort(key=lambda n: n["score"], reverse=True)
    return results[:clamped_limit]


def near_duplicate_titles(db: Database, *, limit: int = 10, min_ratio: float = 0.85) -> list[dict]:
    """#16 merge suggestions for titles that are almost (not exactly) equal.

    Title-level on purpose: a full content-level pair scan is O(n²) over
    384-dim vectors and too slow for an on-demand endpoint; the content
    neighbours live in find_similar and the drawer strip. Titles are
    normalised (case, punctuation, whitespace) so 'Todo – inbox' and
    'todo inbox' collide.
    """
    rows = db.execute(
        """
        SELECT id, title FROM notes
        WHERE trashed_at IS NULL AND archived = 0 AND title != ''
        ORDER BY created_at DESC
        """
    ).fetchall()

    def norm(t: str) -> str:
        cleaned = "".join(ch for ch in t.lower() if ch.isalnum() or ch.isspace())
        return " ".join(cleaned.split())

    suggestions: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    notes = [(r["id"], norm(r["title"]), r["title"]) for r in rows]
    for i, (id_a, norm_a, title_a) in enumerate(notes):
        if not norm_a:
            continue
        for id_b, norm_b, title_b in notes[i + 1 :]:
            if not norm_b or (id_a, id_b) in seen_pairs:
                continue
            ratio = SequenceMatcher(None, norm_a, norm_b).ratio()
            if ratio < min_ratio:
                continue
            seen_pairs.add((id_a, id_b))
            suggestions.append({
                "kind": "merge",
                "note_id": id_a,
                "extra_note_ids": [id_b],
                "title": title_a,
                "reason": f"title {int(ratio * 100)}% like \"{title_b}\" — review for duplicates",
            })
            if len(suggestions) >= limit:
                return suggestions
    return suggestions
