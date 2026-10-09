"""#257: a preferred tag vocabulary, enforced rather than merely suggested.

Steering the prompt is not control. A model asked to prefer "homelab" still
answers "homelab-router" often enough that the tag list stays a mess, so the
vocabulary is applied to the model's output as well.

Similarity comes from `tag_audit.closest_tag`, the same rule the merge UI
uses — one definition of "these two tags are the same word".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .tag_audit import closest_tag

if TYPE_CHECKING:
    from ..config import Config


def preferred_tags(cfg: Config) -> list[str]:
    """The configured vocabulary, deduped, order preserved."""
    seen: list[str] = []
    for raw in (cfg.llm.preferred_tags or "").split(","):
        tag = raw.strip().lstrip("#").lower()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


def tag_prompt(tags: list[str]) -> str:
    """Prompt fragment, or "" when the user has not chosen a vocabulary."""
    if not tags:
        return ""
    return (
        "The user already uses these tags: "
        + ", ".join(tags)
        + ". Prefer them whenever one fits. Only invent a new tag when none of "
        "them does — a near-miss of an existing tag is worse than a reuse."
    )


def apply_preferred_tags(tags: list[str], vocabulary: list[str]) -> list[str]:
    """Snap near-miss tags onto the vocabulary, dropping the duplicates.

    Dedup happens here rather than in `_sanitize` because two *different*
    model tags can now collapse onto one preferred tag, which the sanitizer
    never sees.
    """
    if not vocabulary:
        return tags
    out: list[str] = []
    for tag in tags:
        resolved = closest_tag(tag, vocabulary) or tag
        if resolved not in out:
            out.append(resolved)
    return out
