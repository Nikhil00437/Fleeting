"""#113: resolve a vault file and a database row that disagree.

The conflict is detected by `#122`'s classifier: the file no longer holds the
bytes we last wrote, so somebody edited it in another tool. This module decides
what happens next.

**There is no text merge, and that is a decision rather than a gap.** A three-way
merge needs the common ancestor — the content as it was before either side
changed. Storing that would mean keeping a second copy of every note's text
somewhere that is not the note, which is the thing the whole privacy bundle
exists to avoid. The sync log keeps the *hash* of what we wrote, which is enough
to tell the two sides apart and not enough to blend them. So the choices are:

- **`keep_db`** — the file was ours and is now behind; rewrite it. The usual case
  after an edit in Obsidian that you then undo in the app.
- **`keep_file`** — the file is newer and the words are worth having; import it
  back as a **new** note and leave the original alone. Not an update: overwriting
  the row loses the app-side edits (tags, tasks, summary) that the file never
  carried. Two notes is recoverable; a merged half-and-half note is not.
- **`keep_both`** — write the file's version in as a new note *and* refresh the
  file from the database, so neither side is lost.

**Every resolution writes a sync log entry.** Without that the next comparison
still sees a file it does not recognise, and the conflict reappears — which is how
"resolve" becomes a button that does nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .markdown import (
    hash_text,
    parse_note_md,
    render_note_md,
    sync_note,
    vault_path_for,
)
from .vault_dryrun import classify
from .vault_log import record

log = logging.getLogger("fleeting.vault.conflict")

RESOLUTIONS = ("keep_db", "keep_file", "keep_both")


def detect(cfg: Any, db: Any, limit: int = 500) -> list[dict[str, Any]]:
    """Live conflicts, re-derived rather than read from the log.

    The log records what happened; this reports what is true. A log that has
    never been pruned would show a conflict resolved last week as still open,
    and a list of resolved conflicts nobody can clear is a list people stop
    reading.
    """
    out: list[dict[str, Any]] = []
    for note in db.list_notes(limit=limit):
        entry = classify(cfg, note, db)
        if entry["action"] != "conflict":
            continue
        entry["path"] = str(vault_path_for(cfg, note))
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def _read_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _import_as_note(db: Any, content: str, title_suffix: str = " (from vault)") -> str | None:
    """Turn a vault file into a new note.

    A new row rather than an update: the file never carried the tags, tasks or
    summary the app has been maintaining, so overwriting the row destroys them.
    Two notes is a thing you can undo. A half-and-half note is not.
    """
    parsed = parse_note_md(content)
    note_id = f"vault-{abs(hash((content, title_suffix))) % (10**10):010d}"
    db.insert_note(
        {
            **parsed,
            "id": note_id,
            "title": f"{parsed.get('title') or 'Untitled'}{title_suffix}",
            "source": {"url": "", "from_vault": True},
        }
    )
    db.commit()
    return note_id


def resolve(
    cfg: Any,
    db: Any,
    note_id: str,
    resolution: str,
    bus: Any = None,
) -> dict[str, Any]:
    """Apply one resolution. Raises `ValueError` for an unknown resolution and
    `LookupError` for a note that is not in conflict."""
    if resolution not in RESOLUTIONS:
        raise ValueError(f"unknown resolution {resolution!r}; expected one of {', '.join(RESOLUTIONS)}")

    note = db.get_note(note_id)
    if not note:
        raise LookupError(f"note {note_id} not found")
    path = vault_path_for(cfg, note)
    if classify(cfg, note, db)["action"] != "conflict":
        raise LookupError(f"note {note_id} is not in conflict")

    before = _read_file(path)
    result: dict[str, Any] = {"note_id": note_id, "resolution": resolution}
    created: str | None = None

    if resolution in ("keep_db", "keep_both"):
        # One entry for the *resolution*, then let `sync_note` log the write it
        # actually performs. Logging the resolution separately keeps the
        # conflict on the record — "there was a conflict here" is worth knowing
        # later — and two entries claiming to be the same write would contradict
        # each other about whether anything was in conflict.
        record(
            db,
            note_id,
            str(path),
            f"resolve:{resolution}",
            hash_text(before or ""),
            hash_text(render_note_md(note)),
            conflict=True,
        )
        sync_note(cfg, note, db)

    if resolution in ("keep_file", "keep_both") and before is not None:
        created = _import_as_note(db, before)

    result["created_note_id"] = created
    result["file_updated"] = resolution in ("keep_db", "keep_both")
    if bus is not None:
        if created:
            bus.publish("note.created", {"id": created})
        bus.publish("note.updated", {"id": note_id})
    db.record_audit(
        "vault.resolve",
        f"{resolution} {note_id}",
        {"note_id": note_id, "resolution": resolution, "created": created},
    )
    return result