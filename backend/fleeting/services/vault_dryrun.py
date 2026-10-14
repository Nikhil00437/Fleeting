"""#122: see what the vault sync would do, without doing it.

The mirror writes on every note change. That is right most of the time and
alarming the rest: a folder-mapping rule that puts every note in a new
subdirectory looks, until you look, exactly like a sync that is about to
scatter a few thousand files. And because the first sign of a mistake is a
folder full of misplaced notes, "check first" has to be a real operation rather
than an instruction to go and look at the filesystem.

**The plan is computed, never simulated-and-remembered.** Each note is rendered
in memory and compared with what is on disk *now*, so the answer cannot go stale
between planning and applying — which is the failure mode of a dry run that
records its conclusions and applies them later.

**Five outcomes, and the difference between two of them is the whole feature:**

| outcome | meaning |
|---|---|
| `create` | no file yet |
| `unchanged` | the file is exactly what we would write; skip it |
| `rewrite` | the file differs but we have no record of writing it |
| `conflict` | the file differs from **what we last wrote** — the user edited it |
| `skip` | sensitive notes never reach the vault (#26) |

`rewrite` and `conflict` are different failures. `rewrite` means "this file
predates us or came from elsewhere". `conflict` means "this is our file and a
person has edited it since" — the only one where applying the plan destroys
something somebody typed.

Applying the plan is a separate call that takes the conflicts as a decision, not
a guess. Nothing here writes.
"""

from __future__ import annotations

import logging
from typing import Any

from .markdown import hash_text, render_note_md, vault_path_for
from .vault_log import last_write

log = logging.getLogger("fleeting.vault.dryrun")

# A plan that lists every note in a five-year vault is a wall of text, and the
# counts are what you act on. Samples exist so the shape is recognisable.
PLAN_SAMPLE = 20

# One action per note. `conflict` and `rewrite` are the two that need a human.
ACTIONS = ("create", "unchanged", "rewrite", "conflict", "skip")


def classify(cfg: Any, note: dict, db: Any) -> dict[str, Any]:
    """What would happen to this one note, and why."""
    if note.get("sensitive"):
        # #26: a sensitive note never becomes a plain-text file on disk. The
        # vault outlives the app and is read by other tools.
        return _entry(note, "skip", "sensitive notes never reach the vault")

    try:
        path = vault_path_for(cfg, note)
    except Exception as exc:  # noqa: BLE001
        return _entry(note, "rewrite", f"could not resolve a path: {exc}")

    rendered = render_note_md(note)
    on_disk: str | None = None
    try:
        on_disk = path.read_text(encoding="utf-8")
    except OSError:
        on_disk = None

    if on_disk is None:
        return _entry(note, "create", "no file yet")
    if on_disk == rendered:
        return _entry(note, "unchanged", "the file already matches")

    recorded = last_write(db, str(note.get("id") or "")) if db is not None else None
    if recorded is None:
        # It predates us, or came from somewhere else. Not somebody editing our
        # file — there is no "our file" to have edited.
        return _entry(note, "rewrite", "differs, and we have no record of writing it")
    if recorded.get("hash_after") == hash_text(on_disk):
        # The file still holds exactly what we wrote, and the note has changed
        # since. Ours, untouched, simply behind — an ordinary rewrite.
        return _entry(note, "rewrite", "unchanged on disk; the note has changed since")
    # The file no longer holds what we wrote. Somebody edited it in another tool,
    # and applying the plan would replace their words with ours.
    return _entry(note, "conflict", "edited since we last wrote it")


def _entry(note: dict, action: str, why: str) -> dict[str, Any]:
    return {
        "note_id": note.get("id"),
        "title": note.get("title") or "Untitled",
        "action": action,
        "why": why,
    }


def plan(cfg: Any, notes: list[dict], db: Any = None) -> dict[str, Any]:
    """The whole plan: a count per action, and a sample of each.

    Counts first because that is what you act on — "3 conflicts" is a decision,
    "here are twelve hundred rows" is not.
    """
    entries = [classify(cfg, note, db) for note in notes]
    counts = {action: 0 for action in ACTIONS}
    samples: dict[str, list[dict]] = {action: [] for action in ACTIONS}
    for entry in entries:
        counts[entry["action"]] += 1
        if len(samples[entry["action"]]) < PLAN_SAMPLE:
            samples[entry["action"]].append(entry)
    return {
        "total": len(entries),
        "counts": counts,
        "samples": samples,
        # The one number that decides whether applying this is safe unattended.
        "safe_to_apply": counts["conflict"] == 0,
    }


def plan_all(cfg: Any, db: Any, limit: int = 5000) -> dict[str, Any]:
    """Plan against the whole database.

    `limit` because a vault with a hundred thousand notes should not hang the
    settings page. A plan that silently covers the first N and says "total: N"
    is worse than one that admits it stopped, so the limit is reported.
    """
    notes = db.list_notes(limit=limit)
    result = plan(cfg, notes, db)
    result["scanned"] = len(notes)
    result["truncated"] = len(notes) >= limit
    return result