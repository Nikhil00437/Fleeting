"""#457: a backup index you cannot quietly edit.

#188 writes `<db>.pre-v<N>.bak` before every migration, which leaves a pile of
files with nothing tying them together: no record of what they are, when they
were taken, or whether the one you would restore from is the one that was made.
Restoring the wrong backup is a worse failure than having none.

A plain list of hashes is not enough, because an index is a file and a file can
be edited: rewrite the hash of the backup you replaced and the index still
verifies. So each entry carries the hash of the entry before it —
`entries[i].prev == sha256(entries[i-1])` — and editing or removing one entry
breaks every hash after it. That is what makes it tamper-*evident* rather than
merely tamper-resistant.

Append-only, one JSON object per line, so a partially written index is still a
readable one. A crash mid-write must not destroy the record of the backups that
came before it, which a single JSON document would do.

**What this is not.** It is not a signature and not encryption. Anyone who can
write the index can recompute the whole chain. This detects accidental corruption,
an interrupted write, and casual editing — which is the honest scope, and worth
saying here rather than letting a reader assume more.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Enough history to find a backup from before a bad migration. Older than that
# and the file stops being something anyone opens.
INDEX_CAP = 200

# The fields that make up an entry's own hash. `sha256` (this entry's hash) and
# `prev` (the previous entry's) are excluded — the hash cannot depend on itself.
# `file_sha256` *is* included: if someone swaps the backup and rewrites the entry,
# the entry hash changes too, which is what breaks the chain after it.
_HASHED_FIELDS = ("at", "path", "bytes", "kind", "version", "file_sha256")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _entry_hash(entry: dict[str, Any]) -> str:
    """The hash of one entry's *content*, excluding the hash fields themselves.

    `sort_keys` because a hash over a dict is a hash over an ordering, and JSON
    key order is not guaranteed stable across writers.
    """
    payload = json.dumps({k: entry.get(k) for k in _HASHED_FIELDS}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_all(index_path: str | Path) -> list[dict[str, Any]]:
    """Every readable entry.

    A line that does not parse is skipped rather than raising: a truncated final
    line is the expected shape of a crash mid-write, and refusing to read the
    index because of it would throw away the record of everything before it.
    """
    path = Path(index_path)
    entries: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("path"):
            entries.append(entry)
    return entries


def append(
    index_path: str | Path,
    backup: str | Path,
    *,
    kind: str = "manual",
    version: int | None = None,
) -> dict[str, Any]:
    """Record one backup at the end of the chain, capping the file.

    The write is: read, append, write-temp, rename. A temp file plus `os.replace`
    because a half-written index is worse than a stale one, and the rename is
    atomic within a filesystem.
    """
    path = Path(index_path)
    backup_path = Path(backup)
    entries = read_all(path)
    # Two hashes, deliberately distinct and easy to confuse:
    # `file_sha256` is the backup's bytes; `sha256` is this entry's metadata and
    # is what the *next* entry chains to. Collapsing them makes `verify` compare
    # a file hash against an entry hash and report every backup as corrupt.
    file_hash = _sha256_file(backup_path) if backup_path.exists() else ""
    entry: dict[str, Any] = {
        "at": _now(),
        "path": backup_path.name,
        "bytes": backup_path.stat().st_size if backup_path.exists() else 0,
        "kind": kind,
        "version": version,
        "file_sha256": file_hash,
        "prev": _entry_hash(entries[-1]) if entries else "",
        "sha256": "",
    }
    entry["sha256"] = _entry_hash(entry)
    entries.append(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in entries[-INDEX_CAP:]) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return entry


def _unreadable_lines(index_path: str | Path) -> int:
    """Non-empty lines `read_all` could not use.

    Reported because a garbled or removed line is *silently skipped* by
    `read_all` — which is exactly the tamper case the chain exists to catch. If
    the chain only ever sees the lines that survived, deleting one is invisible.
    A truncated final line after a crash is the benign case and is reported too,
    worded so the two can be told apart.
    """
    try:
        text = Path(index_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    total = sum(1 for line in text.splitlines() if line.strip())
    return max(0, total - len(read_all(index_path)))


def verify(index_path: str | Path, backup_dir: str | Path | None = None) -> list[str]:
    """Problems, as sentences a person can act on. Empty means intact."""
    problems: list[str] = []
    entries = read_all(index_path)
    unreadable = _unreadable_lines(index_path)
    if unreadable:
        problems.append(
            f"{unreadable} line(s) in the index could not be read — the file may have been "
            "edited, or a write was interrupted"
        )
    for i, entry in enumerate(entries):
        name = entry.get("path", "?")
        if i == 0:
            if entry.get("prev"):
                problems.append(f"{name}: first entry claims a predecessor — the chain starts here")
        elif entry.get("prev") != _entry_hash(entries[i - 1]):
            problems.append(
                f"{name}: does not follow the entry before it — "
                "the index was edited, or an entry was removed"
            )
        if _entry_hash(entry) != entry.get("sha256"):
            problems.append(f"{name}: its own contents do not match its hash")

        target = Path(backup_dir or Path(index_path).parent) / name
        if not target.exists():
            problems.append(f"{name}: recorded but missing from disk")
            continue
        try:
            if _sha256_file(target) != entry.get("file_sha256"):
                problems.append(f"{name}: contents on disk do not match the index")
        except OSError as exc:
            problems.append(f"{name}: could not be read ({exc})")
    return problems