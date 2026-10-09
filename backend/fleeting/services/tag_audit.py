"""Tag audit (#425): rare, overlapping and misspelt tag candidates.

Pure string heuristics over `all_tags()` — no embeddings, no LLM. The
"target" of each pair is the tag the merge should keep: the container for
overlaps ("work" ⊂ "workflow" → keep "workflow") and the more frequently
used one for likely misspellings.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database


def closest_tag(candidate: str, vocabulary: list[str], ratio: float = 0.85) -> str | None:
    """The vocabulary entry `candidate` most likely means, or None.

    Two rules, in order. Containment first: 'homelab-router' *contains*
    'homelab', which is the case that actually happens — a model qualifying a
    tag you already use. This is the same container-absorbs-member reasoning
    tag_audit uses below. Then string similarity for genuine misspellings.

    Returns None rather than a poor match: vocabulary control that rewrites
    "sourdough" to "homelab" because the strings share letters is worse than
    no control at all.
    """
    low = candidate.lower()
    exact = next((v for v in vocabulary if v.lower() == low), None)
    if exact:
        return exact

    contained = [v for v in vocabulary if low.startswith(f"{v.lower()}-") or low.startswith(f"{v.lower()}_")]
    if contained:
        # Longest wins, so 'homelab-router' prefers a 'homelab-router' entry
        # over a bare 'homelab' one.
        return max(contained, key=len)

    best, best_score = None, ratio
    for tag in vocabulary:
        score = SequenceMatcher(None, low, tag.lower()).ratio()
        if score > best_score:
            best, best_score = tag, score
    return best


def tag_audit(db: Database, *, limit: int = 20, misspelt_ratio: float = 0.85) -> dict:
    tags = db.all_tags()  # sorted by count DESC
    counts = {t["tag"]: t["count"] for t in tags}
    names = [t["tag"] for t in tags]

    rare = [{"tag": t, "count": c} for t, c in counts.items() if c <= 1][:limit]

    overlapping: list[dict] = []
    misspelt: list[dict] = []
    for i, a in enumerate(names):
        la = a.lower()
        for b in names[i + 1 :]:
            lb = b.lower()
            if la in lb or lb in la:
                # Container wins: 'workflow' absorbs 'work'.
                target = a if len(la) >= len(lb) else b
                overlapping.append({"tags": [a, b], "target": target})
            elif SequenceMatcher(None, la, lb).ratio() >= misspelt_ratio:
                target = a if counts[a] >= counts[b] else b
                misspelt.append({"tags": [a, b], "target": target})
            if len(overlapping) >= limit and len(misspelt) >= limit:
                return {"rare": rare, "overlapping": overlapping[:limit], "misspelt": misspelt[:limit]}

    return {"rare": rare, "overlapping": overlapping[:limit], "misspelt": misspelt[:limit]}
