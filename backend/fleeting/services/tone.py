"""#259 local-only sentiment and urgency flags for sorting.

Neither flag calls a model, and that is the requirement rather than a
shortcut. A flag that changes when the LLM is swapped, or vanishes when LM
Studio is closed, cannot be sorted against — and a note list whose order
quietly changes underneath the user is worse than one with no order at all.

Everything is computed on read. No columns, no migration, no backfill: a
stored flag would need re-deriving on every capture, and the corpus is a
single-user inbox small enough to score in the request.

Both flags return their reasons. An unexplainable flag is one nobody can
correct, which is the whole failure mode of sentiment analysis.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..db import Database

# Urgency is a deadline, so it turns on language about time and on tasks the
# user already gave a due date to. Word lists are matched as whole tokens —
# "urgently" should not fire on "sur gently", and substring matching on short
# words is how a heuristic starts lying.
_URGENT_TOKENS = frozenset({
    "asap", "urgent", "urgently", "immediately", "now", "today", "tonight",
    "eod", "deadline", "overdue", "critical", "blocker", "blocking",
})
_SOON_TOKENS = frozenset({"tomorrow", "soon", "hurry", "quickly", "asap"})

# Two small, opposing lists. This is the ceiling of the feature and it is a
# real one: a lexicon this size will read "sick" as negative and miss
# sarcasm entirely. It is deliberately local and inspectable rather than a
# model's opinion, and it is easy to extend.
_POSITIVE = frozenset({
    "love", "loved", "lovely", "great", "good", "nice", "happy", "wonderful",
    "excited", "excellent", "awesome", "beautiful", "perfect", "worked",
    "shipped", "solved", "thanks", "thank", "win", "best", "enjoy", "fun",
})
_NEGATIVE = frozenset({
    "hate", "hated", "awful", "terrible", "broken", "broke", "bad", "worst",
    "angry", "frustrated", "frustrating", "annoying", "annoyed", "sad",
    "stuck", "failed", "failing", "fail", "wrong", "problem", "bug", "ugh",
})

_LEVELS = {"none": 0, "low": 1, "high": 2}
_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def urgency(note: dict, db: "Database | None" = None, *, today: str | None = None) -> tuple[str, list[str]]:
    """(level, reasons) for how time-pressed a note reads.

    `db` is optional and only used for one thing: whether the note already has
    overdue tasks attached. A note that can be scored from its own words
    alone does not need a database, which keeps this callable from anywhere.
    """
    text = f"{note.get('title') or ''}\n{note.get('raw_text') or ''}\n{note.get('summary') or ''}"
    tokens = _tokens(text)
    reasons: list[str] = []
    level = "none"

    hits = sorted({t for t in tokens if t in _URGENT_TOKENS})
    if hits:
        level = "high"
        reasons.append(f"deadline language: {', '.join(hits)}")
    elif any(t in _SOON_TOKENS for t in tokens):
        level = "low"
        soon = sorted({t for t in tokens if t in _SOON_TOKENS})
        reasons.append(f"time-bound language: {', '.join(soon)}")

    if db is not None and today:
        overdue = _overdue_task_count(db, str(note.get("id") or ""), today)
        if overdue:
            # A date the user already committed to outranks anything the prose
            # merely implies, so this forces the top level rather than nudging.
            level = "high"
            reasons.append(f"{overdue} overdue task(s) attached")

    return level, reasons


def _overdue_task_count(db: "Database", note_id: str, today: str) -> int:
    if not note_id:
        return 0
    row = db.execute(
        "SELECT COUNT(*) AS c FROM tasks WHERE note_id = ? AND done = 0 "
        "AND due_date IS NOT NULL AND TRIM(due_date) != '' AND due_date < ?",
        (note_id, today),
    ).fetchone()
    return int(row["c"] or 0)


def sentiment(note: dict, db: "Database | None" = None) -> tuple[str, list[str]]:
    """(level, reasons) for the mood of a note's own words.

    Ties stay neutral. One word each way is not a signal, and resolving it
    either way would be a coin flip the user then has to inspect.
    """
    text = f"{note.get('title') or ''}\n{note.get('raw_text') or ''}\n{note.get('summary') or ''}"
    tokens = _tokens(text)
    pos = sorted({t for t in tokens if t in _POSITIVE})
    neg = sorted({t for t in tokens if t in _NEGATIVE})

    if not pos and not neg:
        return "neutral", []
    if len(pos) > len(neg):
        return "positive", [f"positive: {', '.join(pos)}"]
    if len(neg) > len(pos):
        return "negative", [f"negative: {', '.join(neg)}"]
    return "neutral", [f"evenly mixed: +{', '.join(pos)} / -{', '.join(neg)}"]


def tone_of(note: dict, db: "Database | None" = None, *, today: str | None = None) -> dict[str, Any]:
    """Both flags for one note, as a dict with their reasons attached."""
    level, reasons = urgency(note, db, today=today)
    mood, mood_why = sentiment(note, db)
    return {
        "urgency": level,
        "urgency_reasons": reasons,
        "sentiment": mood,
        "sentiment_reasons": mood_why,
    }