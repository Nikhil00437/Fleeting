"""Hybrid search service combining SQLite FTS5 keyword matching and vector semantic similarity.

Supports three search modes:
- 'keyword': SQLite FTS5 BM25 ranked full-text search with highlighting.
- 'semantic': Dense vector cosine similarity search using embedded notes.
- 'hybrid': Reciprocal Rank Fusion (RRF) combining keyword and semantic scores.

Provides facet filtering by note type and repository.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from .embeddings import cosine_similarity, embed_text, unpack_vector

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.semantic_search")


def _generate_snippet(note: dict) -> str:
    """Generate a snippet from note summary or raw text (up to 160 chars)."""
    summary = (note.get("summary") or "").strip()
    if summary:
        return summary[:160]
    raw = (note.get("raw_text") or "").strip()
    return raw[:160]


def _note_matches_filter_type(note: dict, filter_type: str | None) -> bool:
    """Check if note matches the specified note type filter."""
    if not filter_type or not filter_type.strip():
        return True
    return str(note.get("type") or "").strip().lower() == filter_type.strip().lower()


def _note_matches_repo(note: dict, repo: str, db: Database | None = None) -> bool:
    """Check if note matches repo via tasks, note source, or tags."""
    target = repo.strip().lower().lstrip("#")
    if not target:
        return True

    # 1. Check tasks / action items in note dict
    action_items = note.get("action_items") or []
    for item in action_items:
        if isinstance(item, dict):
            r = (item.get("repo") or "").strip().lower().lstrip("#")
            if r == target:
                return True

    # Check tasks table directly in DB if available
    note_id = note.get("id")
    if db is not None and note_id:
        try:
            row = db.execute(
                "SELECT 1 FROM tasks WHERE note_id = ? AND LOWER(TRIM(REPLACE(repo, '#', ''))) = ? LIMIT 1",
                (note_id, target),
            ).fetchone()
            if row:
                return True
        except Exception:
            pass

    # 2. Check note source metadata
    source = note.get("source") or {}
    if isinstance(source, dict):
        src_repo = str(source.get("repo") or source.get("repository") or "").strip().lower().lstrip("#")
        if src_repo == target or target in src_repo:
            return True
        src_url = str(source.get("url") or "").lower()
        if f"/{target}" in src_url or f"/{target}.git" in src_url:
            return True

    # 3. Check note tags
    tags = note.get("tags") or []
    for tag in tags:
        clean = str(tag).strip().lower().lstrip("#")
        if clean == target:
            return True

    return False


def hybrid_search(
    db: Database,
    query: str,
    cfg: Config,
    *,
    mode: str = "hybrid",
    limit: int = 50,
    alpha: float = 0.5,
    filter_type: str | None = None,
    repo: str | None = None,
) -> list[dict]:
    """Execute hybrid, keyword, or semantic search across notes with RRF ranking and facet filtering.

    Args:
        db: Database instance.
        query: User search text.
        cfg: App configuration.
        mode: Search mode - 'hybrid' (default), 'keyword', or 'semantic'.
        limit: Maximum results to return (default 50).
        alpha: Hybrid search RRF keyword weight in [0.0, 1.0] (default 0.5).
        filter_type: Filter by note type ('text', 'voice', 'youtube', etc.).
        repo: Filter by repository name associated with note or its tasks.

    Returns:
        List of note dicts sorted by relevance with 'score', 'match_type', and 'snippet'.
    """
    if not query or not query.strip():
        return []

    clamped_limit = min(max(1, int(limit)), 200)
    clamped_alpha = max(0.0, min(1.0, float(alpha)))
    fetch_limit = max(100, clamped_limit * 3) if (filter_type or repo) else clamped_limit * 2
    search_mode = (mode or "hybrid").strip().lower()

    if search_mode == "keyword":
        try:
            kw_results = db.search(query, limit=fetch_limit)
        except Exception as exc:
            log.warning("Keyword FTS search failed for query %r: %s", query, exc)
            kw_results = []

        candidates: list[dict] = []
        for idx, r in enumerate(kw_results):
            note = dict(r)
            if note.get("archived") or note.get("trashed_at"):
                continue
            note["match_type"] = "keyword"
            note["score"] = float(round(1.0 / (1.0 + idx * 0.1), 4))
            candidates.append(note)

        filtered: list[dict] = []
        for note in candidates:
            if filter_type and not _note_matches_filter_type(note, filter_type):
                continue
            if repo and not _note_matches_repo(note, repo, db):
                continue
            filtered.append(note)
            if len(filtered) >= clamped_limit:
                break
        return filtered

    elif search_mode == "semantic":
        query_vec = embed_text(query, cfg)
        all_emb = db.get_all_embeddings()
        scored: list[tuple[str, float]] = []
        for row in all_emb:
            nid = str(row["note_id"])
            try:
                note_vec = unpack_vector(row["embedding"])
            except Exception:
                continue
            sim = cosine_similarity(query_vec, note_vec)
            if sim <= 0.05:
                continue
            scored.append((nid, sim))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[dict] = []
        for nid, sim in scored:
            raw_note = db.get_note(nid)
            if not raw_note:
                continue
            note = dict(raw_note)
            if note.get("archived") or note.get("trashed_at"):
                continue

            note["score"] = float(round(sim, 4))
            note["match_type"] = "semantic"
            if not note.get("snippet"):
                note["snippet"] = _generate_snippet(note)

            if filter_type and not _note_matches_filter_type(note, filter_type):
                continue
            if repo and not _note_matches_repo(note, repo, db):
                continue

            results.append(note)
            if len(results) >= clamped_limit:
                break
        return results

    else:  # mode == "hybrid" (default)
        try:
            kw_results = db.search(query, limit=fetch_limit)
        except Exception as exc:
            log.warning("Keyword FTS search failed for query %r: %s", query, exc)
            kw_results = []

        kw_map: dict[str, tuple[int, dict]] = {}
        for idx, r in enumerate(kw_results):
            nid = str(r["id"])
            if nid not in kw_map:
                kw_map[nid] = (idx + 1, dict(r))

        query_vec = embed_text(query, cfg)
        all_emb = db.get_all_embeddings()
        sem_scored: list[tuple[str, float]] = []
        for row in all_emb:
            nid = str(row["note_id"])
            try:
                note_vec = unpack_vector(row["embedding"])
            except Exception:
                continue
            sim = cosine_similarity(query_vec, note_vec)
            if sim > 0.05:
                sem_scored.append((nid, sim))

        sem_scored.sort(key=lambda x: x[1], reverse=True)
        sem_top = sem_scored[:fetch_limit]

        sem_map: dict[str, tuple[int, float]] = {}
        for idx, (nid, sim) in enumerate(sem_top):
            sem_map[nid] = (idx + 1, sim)

        candidate_ids = list(dict.fromkeys(list(kw_map.keys()) + list(sem_map.keys())))
        if not candidate_ids:
            return []

        candidates: list[dict] = []
        for nid in candidate_ids:
            k_entry = kw_map.get(nid)
            s_entry = sem_map.get(nid)

            k_rank = k_entry[0] if k_entry else None
            s_rank = s_entry[0] if s_entry else None

            k_term = (clamped_alpha / (60.0 + k_rank)) if k_rank is not None else 0.0
            s_term = ((1.0 - clamped_alpha) / (60.0 + s_rank)) if s_rank is not None else 0.0
            rrf_score = k_term + s_term

            if k_entry is not None and s_entry is not None:
                match_type = "hybrid"
            elif k_entry is not None:
                match_type = "keyword"
            else:
                match_type = "semantic"

            if k_entry is not None:
                note = dict(k_entry[1])
            else:
                raw_note = db.get_note(nid)
                if not raw_note:
                    continue
                note = dict(raw_note)

            if note.get("archived") or note.get("trashed_at"):
                continue

            if not note.get("snippet"):
                note["snippet"] = _generate_snippet(note)

            note["match_type"] = match_type
            note["_rrf_score"] = rrf_score
            candidates.append(note)

        candidates.sort(key=lambda n: n["_rrf_score"], reverse=True)
        if not candidates:
            return []

        max_rrf = candidates[0]["_rrf_score"]
        for note in candidates:
            if max_rrf > 0.0:
                note["score"] = float(round(note["_rrf_score"] / max_rrf, 4))
            else:
                note["score"] = 0.0
            note.pop("_rrf_score", None)

        filtered = []
        for note in candidates:
            if filter_type and not _note_matches_filter_type(note, filter_type):
                continue
            if repo and not _note_matches_repo(note, repo, db):
                continue
            filtered.append(note)
            if len(filtered) >= clamped_limit:
                break
        return filtered
