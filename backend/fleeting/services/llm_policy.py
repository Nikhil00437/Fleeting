"""#459: which capture kinds never reach a model.

`notes.sensitive` (#26) is the per-note switch. This is the same promise made
once by source kind, so a capture you did not think about is covered by
configuration rather than by remembering to tick a box.

Configuration rather than inference, on purpose: a heuristic that guesses
"this looks private" misses the source you forgot about, and marks things you
did not mean to hide. Both failures are worse than not guessing.

The list is normalised the same way `preferred_tags` is — stripped, lowercased,
de-duplicated, order preserved — because it is the same kind of hand-typed
setting and should fail in the same predictable ways.

Empty by default. A default that blocked a capture kind would surprise everyone
on upgrade, and "the setting exists but is off" is discoverable in a way "my
voice memos silently stopped being transcribed" is not.
"""

from __future__ import annotations

from ..config import Config


def blocked_types(cfg: Config) -> list[str]:
    """Capture kinds whose text must never reach a model. Empty by default."""
    seen: list[str] = []
    for raw in (cfg.llm.never_use_ai_types or "").split(","):
        kind = raw.strip().lstrip("#").lower()
        if kind and kind not in seen:
            seen.append(kind)
    return seen


def is_blocked(cfg: Config, note_type: str | None) -> bool:
    return (note_type or "").strip().lower() in blocked_types(cfg)
