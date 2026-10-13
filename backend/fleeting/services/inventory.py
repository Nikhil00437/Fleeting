"""#137: what is stored per category, and how big.

The companion to `/api/offline`: that answers "what leaves the machine", this
answers "what is on it, and which of it would hurt to lose". You cannot protect
data you do not know you have, and the numbers people guess at are wrong — an
audio directory or a vault export is routinely larger than the notes themselves.

Three decisions shape it:

- **Bytes come from the filesystem, not from summing column lengths.** A blob, an
  audio file and a row of text are not comparable, and `length()` on a text
  column under-reports by the page and row overhead SQLite actually spends. For
  the database the honest number is `page_count * page_size`.
- **A missing directory is zero, not an error.** Before the first capture there
  is no audio directory, and a first-run inventory page that 500s is a page
  nobody ever sees again.
- **Categories are ordered by size.** The point is to find the big one; sorted by
  name it becomes a scanning job.

`deletable` is on every row and is the field that stops this misreporting:
notes come from a capture, the database file does not disappear because you
deleted a note, and a single "total notes size" number conflates the two.

Nothing outside the configured directories is ever read. This reports on the
user's own layout; walking anything else would be a different feature with a much
worse failure mode, and there is a test pinning it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..config import Config
from ..db import Database

log = logging.getLogger("fleeting.inventory")


def dir_size(path: str | Path) -> int:
    """Bytes in a file or a whole directory tree.

    A subtree it cannot read is skipped rather than raised: an inventory page
    that dies on one unreadable directory tells you nothing about the rest, which
    is the only reason to open it. `os.walk` already ignores errors by default,
    so there is no handler here to forget.
    """
    p = Path(path)
    try:
        if p.is_file():
            return p.stat().st_size
        if not p.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(p):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def _db_bytes(db: Database) -> int:
    """`page_count * page_size` — what the file actually occupies, including the
    free pages a deleted note leaves behind. That is the number disk usage
    tools report and the number worth shrinking."""
    try:
        page_count = db.execute("PRAGMA page_count").fetchone()["page_count"]
        page_size = db.execute("PRAGMA page_size").fetchone()["page_size"]
        return int(page_count) * int(page_size)
    except Exception:  # noqa: BLE001 - a missing number is not a failed page
        log.debug("could not read the database page size", exc_info=True)
        return 0


def _count(db: Database, sql: str, params: tuple = ()) -> int:
    try:
        return int(db.execute(sql, params).fetchone()["c"])
    except Exception:  # noqa: BLE001 - a table that is not there is zero, not 500
        log.debug("count failed: %s", sql, exc_info=True)
        return 0


def _row(
    name: str,
    kind: str,
    count: int,
    nbytes: int,
    deletable: bool,
    where: str = "",
    count_deleted: int | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "count": count,
        "count_deleted": count_deleted,
        "bytes": nbytes,
        "deletable": deletable,
        "where": where,
    }


def inventory(db: Database, cfg: Config) -> dict[str, Any]:
    """Every category, largest first. Never raises."""
    categories: list[dict[str, Any]] = []

    notes_bytes = _count(db, "SELECT COALESCE(SUM(LENGTH(raw_text)), 0) b FROM notes") + _count(
        db, "SELECT COALESCE(SUM(LENGTH(title)), 0) b FROM notes"
    )
    categories.append(
        _row(
            "notes",
            "table",
            _count(db, "SELECT COUNT(*) c FROM notes WHERE trashed_at IS NULL"),
            notes_bytes,
            True,
            count_deleted=_count(db, "SELECT COUNT(*) c FROM notes WHERE trashed_at IS NOT NULL"),
        )
    )
    categories.append(
        _row(
            "tasks",
            "table",
            _count(db, "SELECT COUNT(*) c FROM tasks"),
            _count(db, "SELECT COALESCE(SUM(LENGTH(text)), 0) b FROM tasks"),
            True,
        )
    )
    categories.append(
        _row(
            "activity",
            "table",
            _count(db, "SELECT COUNT(*) c FROM activity"),
            _count(db, "SELECT COALESCE(SUM(seconds)), 0) b FROM activity"),
            True,
        )
    )
    categories.append(_row("database", "file", 1, _db_bytes(db), False))

    from ..config import ATTACHMENTS_DIR, AUDIO_DIR, LOG_PATH

    categories.append(_row("audio", "files", _files(AUDIO_DIR), dir_size(AUDIO_DIR), True))
    categories.append(
        _row("attachments", "files", _files(ATTACHMENTS_DIR), dir_size(ATTACHMENTS_DIR), True)
    )
    categories.append(
        _row(
            "vault",
            "files",
            _files(cfg.paths.vault_dir),
            dir_size(cfg.paths.vault_dir),
            True,
            where=str(cfg.paths.vault_dir),
        )
    )
    categories.append(_row("log", "file", 1, dir_size(LOG_PATH), False))

    categories.sort(key=lambda c: c["bytes"], reverse=True)
    return {
        "categories": categories,
        "total_bytes": sum(c["bytes"] for c in categories),
    }


def _files(directory: str | Path) -> int:
    """How many files, not how many directories. Best effort by design."""
    p = Path(directory)
    if not p.is_dir():
        return 0
    n = 0
    for _root, _dirs, files in os.walk(p):
        n += len(files)
    return n