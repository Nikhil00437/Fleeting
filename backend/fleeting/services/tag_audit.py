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
