"""Activity-aware search: notes *and* what you actually did.

Notes are half the record. The other half — the window titles you worked under,
the commits you made — was already collected for the daily and weekly digests but
was never searchable. So "what was I working on last Tuesday" could only answer
from notes you happened to capture.

Deliberately additive: `/api/search` keeps its exact shape, and this is a
separate endpoint, so the existing notes search is untouched.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..config import Config
from ..db import Database
from .semantic_search import hybrid_search

log = logging.getLogger("fleeting.search")


def persist_commits(
    db: Database, collected: list[dict] | None, *, until: datetime | None = None
) -> int:
    """Store commit subjects from `collect_git_subjects` so they are searchable.

    Accepts both shapes that collection produces: `{"repo", "subjects": [...]}`
    and an already-flattened `{"repo", "subject"}`. Returns rows written.

    Called from the digest paths rather than at query time: shelling out to git
    per search would be far too slow to do on every keystroke.
    """
    if not collected:
        return 0
    when = (until or datetime.now().astimezone()).astimezone()
    stamp = when.isoformat(timespec="seconds")
    written = 0
    for entry in collected:
        if not isinstance(entry, dict):
            continue
        repo = str(entry.get("repo") or "").strip()
        if not repo:
            continue
        subjects = entry.get("subjects")
        if isinstance(subjects, list):
            items = [str(s).strip() for s in subjects if str(s).strip()]
        elif entry.get("subject"):
            items = [str(entry["subject"]).strip()]
        else:
            continue
        author = str(entry.get("author") or "")
        for subject in items:
            try:
                db.record_commit(repo, subject, author, stamp)
                written += 1
            except Exception:
                log.warning("could not record commit %s/%s", repo, subject, exc_info=True)
    return written


async def unified_search(
    db: Database,
    cfg: Config,
    query: str,
    *,
    limit: int = 20,
    since_day: str | None = None,
) -> dict[str, Any]:
    """Search notes, window sessions and commits at once.

    Every bucket is always present in the result — including empty ones — so the
    UI can index into them without null checks, and can say "no commits matched"
    rather than showing nothing at all.

    A failure in one bucket degrades that bucket to empty; it must not take the
    whole search down, because the notes path is the one people depend on.
    """
    clamped = max(1, min(int(limit), 200))
    empty: dict[str, Any] = {"notes": [], "sessions": [], "commits": []}

    if not query or not query.strip():
        return {**empty, "query": query, "total": 0}

    notes: list[dict] = []
    sessions: list[dict] = []
    commits: list[dict] = []

    try:
        notes = hybrid_search(db, query, cfg, mode="hybrid", limit=clamped)
    except Exception:
        log.warning("unified search: notes bucket failed", exc_info=True)

    try:
        sessions = db.search_activity(query, limit=clamped, since_day=since_day)
    except Exception:
        log.warning("unified search: sessions bucket failed", exc_info=True)

    try:
        commits = db.search_commits(query, limit=clamped)
    except Exception:
        log.warning("unified search: commits bucket failed", exc_info=True)

    return {
        "query": query,
        "notes": notes,
        "sessions": sessions,
        "commits": commits,
        "counts": {
            "notes": len(notes),
            "sessions": len(sessions),
            "commits": len(commits),
        },
        "total": len(notes) + len(sessions) + len(commits),
    }
