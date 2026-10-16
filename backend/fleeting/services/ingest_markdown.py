"""#119: import an existing Markdown folder.

The parser behind `services/ingest.py`'s queue. It reads a folder of Markdown —
somebody's existing notes, or an export from another app — and turns each file
into a note that then goes through the ordinary capture pipeline: enrichment,
embedding, tasks. Nothing here calls a model, which is what lets 2,000 files
queue instead of blocking.

**A file already imported is skipped**, keyed on its path. Re-running an import
must not duplicate a year of notes, and "import my notes folder again" is a
thing people do precisely because they are not sure the first run worked.

**One unreadable file does not abandon the rest.** Its failure is counted, the
rest of the folder is imported, and the job records which files failed — the
only way a user finds out *which* of two thousand is broken.

**Imported notes are `generated`.** The app wrote them, the user did not, and
every text heuristic that reads a note — tone, clarity, the entity index — is
wrong on them, because LLM-written prose capitalises for sentences rather than
names. The flag lets those heuristics skip them.

**Files in the vault directory are skipped by default.** Importing your own vault
back into the app duplicates every note the mirror already has, which is the
single most likely way somebody hurts themselves with this button. It is a
setting, not a hard rule, because "I exported my vault and moved it elsewhere" is
a legitimate reason.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import ingest
from .markdown import parse_note_md

log = logging.getLogger("fleeting.ingest.markdown")

KIND = "markdown-folder"

# Per-run ceilings. Both are reported in the job's detail so a partial import is
# visible rather than looking like a complete one.
MAX_FILES = ingest.MAX_FILES_PER_RUN

SKIP_DIRS = {".git", ".obsidian", "node_modules", ".trash", "__pycache__", ".stfolder"}


def resolve(source: str, config_root: Path | None = None) -> Path:
    """Absolute, expanded, with `~` handled.

    Resolved once and stored on the job, because the "already imported" check
    compares strings and `~/notes` and `/home/you/notes` are the same folder
    written two ways.
    """
    path = Path(source).expanduser()
    if not path.is_absolute() and config_root is not None:
        path = config_root / path
    return path.resolve()


def import_note(db: Any, path: Path, source_root: Path) -> str | None:
    """One file → one note. Returns the note id, or None if it was skipped."""
    rel = str(path.relative_to(source_root)) if path.is_relative_to(source_root) else path.name
    if ingest.already_ingested(db, f"file://{path}", KIND):
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OSError(f"could not read {rel}: {exc}") from exc

    parsed = parse_note_md(text)
    note_id = ingest_note(db, parsed, path, rel)
    ingest.mark_ingested(db, f"file://{path}", KIND, parsed.get("title") or path.name)
    return note_id


def ingest_note(db: Any, parsed: dict[str, Any], path: Path, rel: str) -> str:
    """Insert as a pending capture, so the existing pipeline picks it up.

    `pending` is the mechanism behind "run through enrichment and embeddings" —
    the import joins the queue that every capture already goes through rather
    than reimplementing it.
    """
    from ..db import new_id

    note = {
        "id": new_id(),
        "title": parsed.get("title") or path.stem,
        "type": parsed.get("type") or "text",
        "raw_text": parsed.get("raw_text") or "",
        "summary": parsed.get("summary") or "",
        "tags": parsed.get("tags") or [],
        "action_items": parsed.get("action_items") or [],
        "created_at": parsed.get("created_at") or None,
        "status": "pending",
        # The app wrote these, not the user — see the module docstring.
        "generated": 1,
        "source": {
            "imported_from": "markdown-folder",
            "imported_path": rel,
            "imported_id": parsed.get("id"),
        },
    }
    db.insert_note({k: v for k, v in note.items() if v is not None})
    db.commit()
    return note["id"]


@ingest.register(KIND)
def parse_folder(db: Any, cfg: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Run one import job."""
    root = resolve(job["source"])

    # Checked *before* the directory exists: refusing to import your own vault
    # should not depend on whether the vault has been created yet.
    # Importing it duplicates every note the mirror already has, which is the
    # single most likely way somebody hurts themselves with this button.
    vault = Path(getattr(cfg, "vault_dir", "") or "").expanduser().resolve()
    if not getattr(cfg, "ingest_allow_vault", False) and root == vault:
        raise ValueError(
            "that is the vault directory — importing it would duplicate every note "
            "the mirror already has. Set paths.ingest_allow_vault to do it anyway."
        )
    if not root.is_dir():
        raise FileNotFoundError(f"not a directory: {root}")

    imported = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    files = _files(root)

    for path in files:
        try:
            note_id = import_note(db, path, root)
        except Exception as exc:  # noqa: BLE001
            # One unreadable file must not abandon the other 1,999.
            log.warning("import failed for %s: %s", path, exc)
            failed.append({"file": str(path.relative_to(root)), "error": str(exc)})
            continue
        if note_id:
            imported += 1
        else:
            skipped += 1

    return {
        # An empty folder is a successful import of nothing. Reporting it as
        # failed is the same mistake as a dialog offering to delete nothing.
        "status": ingest.DONE,
        "detail": {
            "root": str(root),
            "found": len(files),
            "imported": imported,
            "skipped": skipped,
            "failed": failed[:20],
            "failed_count": len(failed),
            "truncated": len(files) >= MAX_FILES,
            "explains": (
                "Files were added as pending captures, so enrichment and embeddings "
                "happen on the normal pipeline."
            ),
        },
        "error": f"{len(failed)} file(s) could not be imported" if failed else None,
    }


def _files(root: Path, limit: int = MAX_FILES) -> list[Path]:
    out: list[Path] = []
    stack = [(root, 0)]
    while stack and len(out) < limit:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            log.warning("could not read %s: %s", current, exc)
            continue
        for entry in entries:
            if len(out) >= limit:
                break
            if entry.is_dir():
                if entry.name in SKIP_DIRS or depth >= 8:
                    continue
                stack.append((entry, depth + 1))
            elif entry.suffix.lower() in (".md", ".markdown"):
                out.append(entry)
    return sorted(out)


def preview(db: Any, cfg: Any, source: str) -> dict[str, Any]:
    """What an import would do, without doing it.

    Same reason as the vault dry run: the button that imports a folder is one
    click away from two thousand notes, and a person should be able to see the
    shape of it first.
    """
    root = resolve(source)
    files = _files(root) if root.is_dir() else []
    new = [f for f in files if not ingest.already_ingested(db, f"file://{f}", KIND)]
    return {
        "root": str(root),
        "exists": root.is_dir(),
        "found": len(files),
        "would_import": len(new),
        "already_imported": len(files) - len(new),
        "truncated": len(files) >= MAX_FILES,
        "sample": [f.name for f in new[:10]],
        "explains": (
            "Each file becomes one note and joins the normal pipeline, so it gets "
            "enrichment, tags, tasks and an embedding."
        ),
    }