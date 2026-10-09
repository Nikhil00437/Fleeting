"""#263: the hallucination guard.

Every sentence of a generated summary gets checked against the text it was
generated from, and unsupported sentences are reported as such. Matching is
token overlap, not a model call — a guard that asks the model to grade its
own output is not a guard.

`SUPPORT_RATIO` is a calibration knob, not a constant of nature. It is set
where a restatement usually shares most of its content words, and it is the
first thing to move if summaries start being flagged too often or claims
slip through.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database

# Share of a claim's content words that must appear in the source sentence.
# 0.7 tolerates restatement ("is running" / "is running right now") while
# rejecting a long sentence that merely shares a few nouns.
SUPPORT_RATIO = 0.7

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]+")

# Words too common to carry meaning. Without these, "the note is about the
# router" scores high against any sentence containing "the" or "is".
STOPWORDS = frozenset("""
a an the and or but if then than that this these those there here
is are was were be been being am do does did done doing have has had
to of in on at by for with from into over under about as it its
i we you he she they them me my our your their his her
not no yes so such very just also too can could should would will shall may might must
""".split())


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def supported_ratio(claim: str, source: str) -> float:
    """Share of the claim's content words that occur in `source`.

    0.0 when the claim has no content words at all — a ratio over an empty
    numerator would report perfect support for a sentence that says nothing.
    """
    claim_words = _content_words(claim)
    if not claim_words:
        return 0.0
    source_words = set(_content_words(source))
    hits = sum(1 for w in claim_words if w in source_words)
    return hits / len(claim_words)


def _sentences(text: str) -> list[str]:
    """Split into candidate claims, dropping markdown scaffolding.

    A generated summary is mostly structure — headers, bullets, rules — and
    none of that is a factual claim to be verified.
    """
    out: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        line = raw.strip().strip("*#>-_ ").strip()
        line = re.sub(r"^\[[ xX]\]\s*", "", line)
        if len(_content_words(line)) < 2:
            continue
        out.append(line)
    return out


def verify_claims(summary: str, source: str) -> list[dict]:
    """Check each summary sentence against the note it summarises.

    The cited `span` is the single source sentence with the best overlap, not
    the whole note: a citation that points at 4000 characters cites nothing.
    """
    source_sentences = _sentences(source) or ([source.strip()] if source.strip() else [])
    claims: list[dict] = []
    for sentence in _sentences(summary):
        best_span, best_score = None, 0.0
        for span in source_sentences:
            score = supported_ratio(sentence, span)
            if score > best_score:
                best_span, best_score = span, score
        supported = best_score >= SUPPORT_RATIO
        claims.append({
            "text": sentence,
            "supported": supported,
            "span": best_span if supported else None,
        })
    return claims


def unverified(claims: list[dict] | None) -> list[dict]:
    """The unsupported subset — what the drawer flags."""
    return [c for c in (claims or []) if not c.get("supported")]
