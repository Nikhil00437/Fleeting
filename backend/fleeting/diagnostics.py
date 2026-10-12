"""#395: assemble something you can paste into a bug report.

Logs, redacted config, version, platform, database size — the three things a
maintainer asks for, gathered in one click.

The part that deserves care is redaction, because a bundle is *designed* to
leave the machine: it gets attached to an issue or pasted into chat, which is
the least private place a secret can end up. This config holds an LLM API key, a
bearer token guarding the app's own API, and a HuggingFace token.

Redaction is a **denylist over the whole config**, not a whitelist of fields to
include, and that choice is the safety property: a whitelist has to be edited
every time a field is added, and the field you forget is the one that leaks.
A denylist redacts a new secret-bearing field by default, so a mistake errs
toward hiding something rather than publishing it.

The denylist itself is a denylist: any field whose *name* contains a hint is
treated as a secret even if this module has never heard of it.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from .config import Config

# Substrings of a field name that make it a secret. Matched case-insensitively
# against the whole name, so `my_own_password` is caught alongside `api_key`.
SECRET_HINTS = frozenset(
    {"key", "token", "secret", "password", "passwd", "credential", "cookie"}
)

SET = "<set>"
_LEVELS = {name: num for name, num in logging.getLevelNamesMapping().items()}


def _is_secret(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in SECRET_HINTS)


def redact_config(cfg: Config) -> dict[str, Any]:
    """The whole config, with anything that looks like a secret replaced.

    Not a whitelist of safe fields. See the module docstring: a whitelist has
    to be extended every time a field is added, and the field nobody remembered
    is the one that leaks into a public issue.
    """
    out: dict[str, Any] = {}
    for section_name in _section_names(cfg):
        section = getattr(cfg, section_name, None)
        if not is_dataclass(section):
            continue
        out[section_name] = {
            f.name: (SET if _is_secret(f.name) and getattr(section, f.name) else
                     "" if _is_secret(f.name) else getattr(section, f.name))
            for f in fields(section)
        }
    # Anything a hand-edited config added that is not a dataclass field. Rare,
    # but a key named `api_key` must not slip through just because it is not in
    # the schema.
    for key, value in getattr(cfg, "_extra", {}).items():
        if _is_secret(key) and value:
            out[key] = SET
    return out


def _section_names(cfg: Config) -> list[str]:
    return [f.name for f in fields(cfg)]


def tail_log(
    path: Path | str,
    *,
    min_level: str = "WARNING",
    limit: int = 200,
    max_bytes: int = 512_000,
) -> list[dict[str, Any]]:
    """The last `limit` records at or above `min_level`, newest last.

    Reads only the tail of the file: the user's log reached 6.2 MB before #389
    bounded it, and a bundle that embeds all of it is an attachment nobody
    wants. JSON lines are parsed; the default text format is kept as a raw
    message, because the common case is a log the user did not set to JSON.
    """
    path = Path(path)
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            blob = fh.read()
    except OSError:
        return []

    floor = _LEVELS.get(str(min_level).upper(), logging.WARNING)
    out: list[dict[str, Any]] = []
    for raw in blob.splitlines():
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        entry = _parse_line(line)
        if entry is None:
            continue
        if _LEVELS.get(str(entry.get("level", "")).upper(), logging.INFO) < floor:
            continue
        out.append(entry)
    return out[-limit:]


def _parse_line(line: str) -> dict[str, Any] | None:
    """A JSON line, or a text log line reduced to level + message.

    `None` means "not a record" — a partial line from a log still being
    written, or a rotated fragment.
    """
    if line.startswith("{"):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return None  # a truncated tail, not a failure
        return parsed if isinstance(parsed, dict) else None
    # "2026-10-12 10:00:00,000 WARNING fleeting.x: something odd" — the asctime
    # is two space-separated fields, so the logger name and message are the
    # fourth.
    parts = line.split(" ", 3)
    if len(parts) < 4:
        return None
    logger, _, message = parts[3].partition(":")
    return {"level": parts[2], "logger": logger.strip(), "message": message.strip()}


def build_bundle(
    *,
    cfg: Config,
    log_path: Path | str,
    db_path: Path | str,
    min_level: str = "WARNING",
    limit: int = 200,
) -> dict[str, Any]:
    """Everything a maintainer asks for, in one JSON-serialisable object."""
    from . import __version__

    db_path = Path(db_path)
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "config": redact_config(cfg),
        "log": tail_log(log_path, min_level=min_level, limit=limit),
        "database": {
            "path": str(db_path),
            "exists": db_path.exists(),
            "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        },
    }