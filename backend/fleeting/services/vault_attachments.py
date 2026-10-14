"""#120: copy a note's attachments into the vault, next to the note.

The note file lands in `2026/2026-01-02 fleeting-n1.md`; its images land in
`attachments/2026-01-02 fleeting-n1/` and the note gets a relative link to them.

**Relative, and that is the whole design constraint.** A vault is meant to be
synced, zipped and moved. An absolute `file:///home/you/...` link works on this
machine and is broken everywhere else, including in the copy somebody emails
themselves. So the link is computed from the two vault paths and nothing else.

**A sensitive note copies nothing.** Same rule as the note file itself (#26): the
vault is a plain-text copy that outlives the app and is read by other tools. An
attachment to a sensitive note is the same leak one directory level down.

**Attachments are copied, not moved, and not hard-linked.** A hard link would be
instant and would make editing the attachment in the vault silently edit the
app's copy — two files that look independent and are not. Moving would delete
the app's only copy, and the vault may be a different machine.

**The plan is visible before it runs.** `plan_attachments` reports what would be
copied, skipped and already-present, for the same reason #122 exists: a sync that
copies a few hundred files without saying so is a sync you cannot undo cheaply.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .markdown import note_filename

log = logging.getLogger("fleeting.vault.attachments")

# Where they go inside the vault, relative to the note's own folder.
ATTACHMENT_DIRNAME = "attachments"

# A sample per outcome, for the same reason the dry run has one.
PLAN_SAMPLE = 20


def _vault(cfg: Any) -> Path:
    from ..config import expand_path

    return expand_path(cfg.vault_dir)


def safe_name(filename: str, fallback: str = "file") -> str:
    """An attachment filename safe to put in a path.

    Filenames come from an upload and from `Content-Disposition`, so they are
    user input twice over: `../../.ssh/authorized_keys` is a real header value.
    Slugified, with the extension preserved so the vault shows an image as an
    image.
    """
    from .vault_layout import slug

    name = Path(str(filename or "")).name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    safe_stem = slug(stem) or fallback
    return f"{safe_stem}.{slug(ext)}" if ext else safe_stem


def _rows(db: Any, note_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in db.execute(
            "SELECT id, filename, path, size FROM note_attachments WHERE note_id = ? ORDER BY filename",
            (note_id,),
        )
    ]


def _source(root: Any, row: dict[str, Any]) -> Path:
    """The attachment on disk, whether `path` is absolute or relative to root.

    A row written by an older version may hold either, and a missing file here is
    a warning rather than an error — the row outlives the file.
    """
    stored = Path(str(row.get("path") or ""))
    return stored if stored.is_absolute() else Path(root) / stored


def plan(cfg: Any, db: Any, note: dict, attachments_root_dir: Any = None) -> dict[str, Any]:
    """What copying this note's attachments would do."""
    if note.get("sensitive"):
        # Same keys as the normal branch. A result whose shape depends on why it
        # was empty is one every caller has to guard, and the unguarded one
        # raises `KeyError` at the worst moment.
        return {
            "note_id": note.get("id"),
            "skipped": "sensitive",
            "copy": [],
            "present": [],
            "missing": [],
            "counts": {"copy": 0, "present": 0, "missing": 0},
            "folder": "",
        }

    target_dir = _vault(cfg) / ATTACHMENT_DIRNAME / Path(note_filename(note)).stem
    root = attachments_root_dir if attachments_root_dir is not None else _attachments_root()
    copy: list[dict[str, Any]] = []
    present: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for row in _rows(db, str(note.get("id"))):
        source = _source(root, row)
        entry = {"filename": row["filename"], "safe": safe_name(row["filename"])}
        if not source.exists():
            missing.append(entry)
            continue
        target = target_dir / entry["safe"]
        if target.exists() and target.stat().st_size == source.stat().st_size:
            present.append(entry)
        else:
            copy.append(entry)
    return {
        "note_id": note.get("id"),
        "folder": str(target_dir),
        "copy": copy[:PLAN_SAMPLE],
        "present": present[:PLAN_SAMPLE],
        "missing": missing[:PLAN_SAMPLE],
        "counts": {"copy": len(copy), "present": len(present), "missing": len(missing)},
    }


def _attachments_root() -> Path:
    from ..config import ATTACHMENTS_DIR

    return Path(ATTACHMENTS_DIR)


def link_lines(note: dict, entries: list[dict[str, Any]] | None = None) -> list[str]:
    """The markdown links for a note's attachments. Relative, always.

    `entries` defaults to the note's own attachment rows, so the renderer does
    not have to know where they come from.
    """
    if entries is None:
        entries = [{"safe": safe_name(f)} for f in (note.get("attachments") or [])]
    if not entries:
        return []
    stem = Path(note_filename(note)).stem
    return [f"![[{ATTACHMENT_DIRNAME}/{stem}/{e['safe']}]]" for e in entries]


def copy_attachments(
    cfg: Any, db: Any, note: dict, attachments_root_dir: Any = None
) -> dict[str, Any]:
    """Copy the attachments. Idempotent: an unchanged file is left alone.

    Copy rather than hard-link — a hard link would make editing the attachment
    in the vault silently edit the app's copy, which is two files that look
    independent and are not — and never move, because the vault may be a
    different machine and the app's copy is the only one there.
    """
    detail = plan(cfg, db, note, attachments_root_dir)
    if detail.get("skipped"):
        return {"ok": True, "copied": [], **detail}

    root = attachments_root_dir if attachments_root_dir is not None else _attachments_root()
    target_dir = Path(detail["folder"])
    copied: list[str] = []
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("could not create %s: %s", target_dir, exc)
        return {"ok": False, "error": str(exc), **detail}

    for row in _rows(db, str(note.get("id"))):
        source = _source(root, row)
        name = safe_name(row["filename"])
        if not source.exists():
            continue
        target = target_dir / name
        if target.exists() and target.stat().st_size == source.stat().st_size:
            continue
        try:
            shutil.copy2(source, target)
            copied.append(name)
        except OSError as exc:
            log.warning("could not copy attachment %s: %s", source.name, exc)
    return {"ok": True, "copied": copied, **detail}


def remove_attachments(cfg: Any, note: dict) -> list[str]:
    """Drop this note's attachment folder. Used when a note is trashed."""
    folder = _vault(cfg) / ATTACHMENT_DIRNAME / Path(note_filename(note)).stem
    try:
        if not folder.is_dir():
            return []
        removed = [p.name for p in folder.iterdir()]
        shutil.rmtree(folder)
        return removed
    except OSError as exc:
        log.warning("could not remove %s: %s", folder, exc)
        return []
