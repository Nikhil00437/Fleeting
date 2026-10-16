"""#118: is the vault in the state the app thinks it is?

Four questions, each of which has a different failure behind it:

- **Notes with no file.** The mirror stopped writing — sync is off, the folder is
  not writable, the template changed and nothing re-synced. The vault is a copy,
  so this is "the backup is stale", not "the notes are gone".
- **Orphan files.** Markdown in the vault that no note claims. Usually files the
  user added by hand or another tool wrote. Also the place a *mistaken* delete
  shows up, so they are reported with their paths rather than counted.
- **Broken `[[links]]`.** A wiki-link to a note that was deleted, or renamed
  outside the app. `[[x]]` resolution is not this app's business — Obsidian's
  rules differ — so a link counts as broken only when **no file with that name
  exists anywhere in the vault**, which is a conservative answer.
- **Files with no frontmatter.** Written by something other than this app, or by
  a hand edit that stripped the block. Without an `id:` they cannot be imported
  back, which is the actual cost.

Everything is **bounded** and every count is paired with a sample. A health report
that walks a five-year vault without a ceiling hangs the settings page, and one
that returns a bare number tells you nothing you can act on.

**It never repairs anything.** A report that silently deleted orphans would be a
second, un-audited destructive path, and "clean up my vault" is exactly the
request that goes wrong while someone is not looking.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .markdown import vault_path_for

log = logging.getLogger("fleeting.vault.health")

# A vault can be enormous. Each ceiling is separate because each of these walks a
# different thing, and one shared number would let a huge notes table hide a huge
# file tree.
MAX_NOTES = 5000
MAX_FILES = 2000
MAX_SAMPLES = 20
MAX_DEPTH = 6

# `[[target|alias]]` and `[[target#heading]]` both link to `target`.
_WIKILINK = re.compile(r"\[\[([^\]|#]+)")

# Markdown this app never writes, but a user's vault is full of.
_SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", ".stfolder"}


def _vault_root(cfg: Any) -> Path:
    from ..config import expand_path

    return expand_path(cfg.vault_dir)


def _walk(root: Path, cap: int) -> list[Path]:
    """Markdown files under `root`, bounded in both depth and count."""
    if not root.is_dir():
        return []
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(found) < cap:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if len(found) >= cap:
                break
            if entry.is_dir():
                if entry.name in _SKIP_DIRS or depth >= MAX_DEPTH:
                    continue
                stack.append((entry, depth + 1))
            elif entry.suffix.lower() == ".md":
                found.append(entry)
    return found


def _note_ids(path: Path) -> set[str]:
    """The `id:` value from a file's frontmatter, or None if there is none."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2048]
    except OSError:
        return None
    if not head.lstrip().startswith("---"):
        return None
    match = re.search(r"^id:\s*(\S+)", head, re.MULTILINE)
    if not match:
        return None
    return {match.group(1).strip("\"'")}


def _has_frontmatter(path: Path) -> bool:
    try:
        return path.read_text(encoding="utf-8", errors="replace").lstrip().startswith("---")
    except OSError:
        return False


def scan(cfg: Any, db: Any) -> dict[str, Any]:
    """The whole report. Never raises — a health page that 500s tells you nothing
    about your vault, which is the one thing it exists to tell you."""
    root = _vault_root(cfg)
    files = _walk(root, MAX_FILES)
    claimed: set[str] = set()
    by_stem: dict[str, list[Path]] = {}
    for path in files:
        by_stem.setdefault(path.stem, []).append(path)

    notes_without_file: list[dict[str, Any]] = []
    known_files: set[Path] = set()
    try:
        notes = db.list_notes(limit=MAX_NOTES)
    except Exception:  # noqa: BLE001
        log.warning("vault health: could not list notes", exc_info=True)
        notes = []

    for note in notes:
        # No `trashed_at` check here: `list_notes()` excludes trashed notes
        # already. It used to, and the check was dead code wearing a comment
        # about a permanent unfixable warning — a guard that prevents nothing is
        # worse than no guard, because the next reader believes it works.
        try:
            expected = vault_path_for(cfg, note)
        except Exception:  # noqa: BLE001
            continue
        known_files.add(expected)
        if not expected.exists():
            if len(notes_without_file) < MAX_SAMPLES:
                notes_without_file.append({"id": note.get("id"), "title": note.get("title"), "path": str(expected)})

    orphans: list[dict[str, Any]] = []
    no_frontmatter: list[dict[str, Any]] = []
    from .daily_note import is_daily_file

    for path in files:
        if is_daily_file(path):
            # #117's daily index. It has no `id:` by design — it is an index, not
            # a note — and without this it would be one guaranteed orphan per day,
            # which is how a health report stops being read.
            continue
        ids = _note_ids(path)
        if ids:
            claimed |= ids
        elif path not in known_files:
            if len(orphans) < MAX_SAMPLES:
                orphans.append({"path": str(path.relative_to(root)), "stem": path.stem})
        if not _has_frontmatter(path) and len(no_frontmatter) < MAX_SAMPLES:
            no_frontmatter.append({"path": str(path.relative_to(root))})

    broken = _broken_links(files, by_stem)

    return {
        "vault": str(root),
        "exists": root.is_dir(),
        "files": len(files),
        "notes": len(notes),
        # A file the app claims by path but that carries no `id:` is still
        # "ours" — `known_files` is the authoritative claim, `claimed` the
        # frontmatter one. An orphan is a file neither agrees is ours.
        "notes_without_file": len(notes_without_file),
        "notes_without_file_sample": notes_without_file,
        "orphan_files": len(orphans),
        "orphan_files_sample": orphans,
        "broken_links": len(broken),
        "broken_links_sample": broken,
        "files_without_frontmatter": len(no_frontmatter),
        "files_without_frontmatter_sample": no_frontmatter,
        "truncated": len(files) >= MAX_FILES or len(notes) >= MAX_NOTES,
        "repairs": "none — this report never deletes or moves anything",
        "healthy": not notes_without_file and not orphans and not broken,
    }


def _broken_links(files: list[Path], by_stem: dict[str, list[Path]]) -> list[dict[str, Any]]:
    """`[[links]]` whose target exists nowhere in the vault.

    Deliberately conservative: a link counts as broken only when no file of that
    name exists at all. Obsidian resolves links by shortest path, by full path and
    by heading, and duplicating those rules here would produce warnings the user
    has learned to ignore.
    """
    out: list[dict[str, Any]] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in _WIKILINK.findall(text):
            target = raw.strip()
            if not target:
                continue
            # One check, not two. `Path(x).name` covers both the bare-stem form
            # and the path form, so an exact `target in by_stem` above it was
            # redundant — and a redundant guard is one somebody eventually
            # removes, or one that hides the line that actually does the work.
            # The regex also stops at `|`, so an alias never reaches here.
            if Path(target).name in by_stem:
                continue
            if len(out) >= MAX_SAMPLES:
                return out
            out.append({"from": path.stem, "target": target})
    return out