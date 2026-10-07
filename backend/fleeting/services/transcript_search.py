"""#319: search voice-note transcripts with word timestamps.

raw_text on a voice note IS the transcript, so FTS already finds the note;
what FTS cannot give is *where in the audio* — that lives in whisper's word
timestamps on source.transcription.words ([{w, s, e}]). This module maps
query matches back onto word indices so the UI can jump the player.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .query_parser import ParsedQuery, parse_query

if TYPE_CHECKING:
    from ..db import Database

log = logging.getLogger("fleeting.transcript_search")

# Notes whose transcript words are missing/malformed are skipped silently —
# voice captures processed before whisper word timestamps may have none.


def _words_of(note: dict) -> list[dict]:
    src = note.get("source") or {}
    if isinstance(src, str):
        return []
    words = (src.get("transcription") or {}).get("words") or []
    if not isinstance(words, list):
        return []
    return [w for w in words if isinstance(w, dict) and w.get("w") is not None]


def word_hits(
    words: list[dict],
    terms: list[str],
    phrases: list[str],
    *,
    max_hits: int = 5,
    context: int = 3,
) -> list[dict]:
    """Timestamped matches: the first word of each match anchors `t`, and the
    text is a few words of spoken context. Terms match word-wise (substring,
    like the FTS prefix leg), phrases match across the joined transcript."""
    if not words or not (terms or phrases):
        return []

    lowered = [str(w["w"]).lower() for w in words]

    positions: set[int] = set()
    for term in terms:
        needle = term.lower()
        for i, word in enumerate(lowered):
            if needle in word:
                positions.add(i)
    for phrase in phrases:
        needle = phrase.lower()
        if not needle.strip():
            continue
        joined = " ".join(lowered)
        # Map each occurrence's character offset back to a word index by
        # counting the spaces before it.
        start = 0
        while True:
            idx = joined.find(needle, start)
            if idx < 0:
                break
            positions.add(joined.count(" ", 0, idx))
            start = idx + 1

    hits: list[dict] = []
    seen: set[int] = set()
    for i in sorted(positions, key=lambda x: float(words[x].get("s") or 0.0)):
        # Skip matches already covered by a previous hit's context window.
        if any(abs(i - s) <= context for s in seen):
            continue
        seen.add(i)
        lo, hi = max(0, i - context), min(len(words), i + context + 1)
        hits.append({
            "t": float(words[i].get("s") or 0.0),
            "text": " ".join(str(words[j]["w"]) for j in range(lo, hi)),
        })
        if len(hits) >= max_hits:
            break
    return hits


def transcript_search(
    db: Database,
    query: str,
    *,
    parsed: ParsedQuery | None = None,
    limit: int = 10,
    hits_per_note: int = 5,
) -> list[dict]:
    """Voice notes whose transcript matches, with timestamped hits."""
    p = parsed or parse_query(query)
    terms = list(p.terms) + list(p.phrases)
    if p.near:
        terms += [p.near[0], p.near[1]]
    if not terms:
        return []

    # Candidate notes come from the FTS leg over the transcript text;
    # operator filters apply too — a transcript search honours the same
    # grammar instead of inventing its own.
    candidates = db.search(" ".join(terms), limit=max(limit * 4, 40), parsed=p)
    results: list[dict] = []
    for note in candidates:
        if note.get("archived"):
            continue
        if str(note.get("type") or "") != "voice":
            continue
        words = _words_of(note)
        if not words:
            continue
        hits = word_hits(words, p.terms, p.phrases, max_hits=hits_per_note)
        if not hits:
            continue
        results.append({"note": note, "hits": hits})
        if len(results) >= max(1, int(limit)):
            break
    return results
