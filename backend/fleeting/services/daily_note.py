"""#117: a `Daily/YYYY-MM-DD.md` index, appended to as notes arrive.

Journaling tools want one file per day with links to everything that happened.
Rather than make the user copy notes across, the mirror keeps one file per day
and adds a line per note.

**The daily file is the app's, and says so.** It carries `daily: true` in its
frontmatter, which is what keeps #118 from reporting it as an orphan on every
single day forever. A health report with one guaranteed false positive per day is
a health report people stop opening.

**Appending is idempotent, keyed on the note id.** Re-syncing a note must not add
a second line for it — that is the difference between a journal and a spam
folder — so the write is "add unless the id is already there", decided by reading
the file rather than by trusting a flag.

**Lines are removed when the note is trashed.** A link to a deleted note is a
dangling link, and #118 would report it as broken forever. Removing the line keeps
the vault's own health report honest; leaving it makes every deletion a permanent
false alarm.

**A user's own lines are never touched.** Only the line this app wrote, found by
its marker, is rewritten. Somebody's hand-written `## Ideas` section in a daily
note is not ours to reorganise.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .markdown import vault_path_for

log = logging.getLogger("fleeting.vault.daily")

DEFAULT_DIRNAME = "Daily"

# The marker on every line this app writes. It is how a line is identified as
# ours on removal, so it has to survive into the file.
MARKER = "<!-- fleeting -->"

HEADER = """---
app: fleeting
daily: true
date: {date}
---

# {date}
"""


def _vault(cfg: Any) -> Path:
    from ..config import expand_path

    return expand_path(cfg.vault_dir)


def dirname(cfg: Any) -> str:
    """The folder, or "" when the feature is off.

    Off by default, and the default is "" rather than "Daily": a `Daily/`
    folder appearing in a vault that never asked for one is a surprise, and this
    is a convention rather than a requirement.
    """
    value = getattr(cfg, "vault_daily_dir", "")
    return str(value).strip() if value is not None else ""


def date_of(note: dict) -> str:
    """The local day, via the same helper everything else uses.

    `created_at` is UTC and "today" is a local judgement — routing this through
    `date_tag` is what stops a capture at 00:30 landing on yesterday's file.
    """
    from .calendar_svc import date_tag

    return date_tag(note.get("created_at") or note.get("created")) or "undated"


def path_for(cfg: Any, note: dict) -> Path | None:
    folder = dirname(cfg)
    if not folder:
        return None
    return _vault(cfg) / folder / f"{date_of(note)}.md"


def _link_for(cfg: Any, note: dict) -> str:
    """A vault-relative link, so the daily file works wherever the vault is."""
    note_path = vault_path_for(cfg, note)
    try:
        target = note_path.relative_to(_vault(cfg))
    except ValueError:
        target = Path(note_path.name)
    title = (note.get("title") or "Untitled").replace("|", "/").replace("[", "(").replace("]", ")")
    return f"- [[{target.as_posix()}|{title}]] {MARKER}"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def append(cfg: Any, note: dict) -> Path | None:
    """Add this note's line, unless it is already there."""
    path = path_for(cfg, note)
    if path is None or note.get("sensitive"):
        return None
    if note.get("trashed_at"):
        # The vault sync runs in the pipeline, *after* the note reaches `done`. A
        # note trashed in that window would otherwise get its daily line written
        # after `remove` had already taken it away — a dangling link that #118
        # then reports as broken forever. The race is real, not theoretical: it
        # showed up as a flaky test in the full suite before this check existed.
        return None
    line = _link_for(cfg, note)
    text = _read(path)
    if line in text:
        return path
    body = text if text else HEADER.format(date=date_of(note))
    if not body.endswith("\n"):
        body += "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        written = body + line + "\n"
        path.write_text(written, encoding="utf-8")
        # Echo suppression, the same as `sync_note`. Without this the watcher
        # sees a file the app just wrote and imports it back as a note — and a
        # note it imports is itself synced, and indexed again.
        from .markdown import sync_registry

        sync_registry.register(path, written)
    except OSError as exc:
        # A daily index is a convenience. Failing the note's sync because an
        # index could not be appended would be a worse trade than a missing line.
        log.warning("could not append to daily note %s: %s", path, exc)
        return None
    return path


def remove(cfg: Any, note: dict) -> bool:
    """Drop this note's line. Only the line carrying our marker."""
    path = path_for(cfg, note)
    if path is None:
        return False
    text = _read(path)
    if not text:
        return False
    kept = [
        line
        for line in text.splitlines()
        if not (line.lstrip().startswith("- [[") and MARKER in line and note.get("id") and note["id"] in line)
    ]
    if len(kept) == len(text.splitlines()):
        return False
    try:
        path.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("could not rewrite daily note %s: %s", path, exc)
        return False
    return True


def is_daily_file(path: Path) -> bool:
    """Does this file belong to the daily-note feature?

    Read by #118 so the daily folder does not fill the health report with an
    orphan per day.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:512]
    except OSError:
        return False
    return "daily: true" in head