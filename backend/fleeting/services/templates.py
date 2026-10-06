"""Capture templates (#1) and HUD output modes (#427, shipped together).

Templates live as a small JSON blob next to config.toml — the bundle's
    `[template.idea]` TOML section would fight the comment-preserving
config writer, and a separate file stays hand-editable without touching
settings serialization.

    [{ "idea": {"type": "idea", "tags": ["idea"], "prompt": "...", "mode": "cleaned"}}]
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR

log = logging.getLogger("fleeting.templates")

TEMPLATES_PATH = CONFIG_DIR / "templates.json"

OUTPUT_MODES = ("raw", "cleaned", "bullets")

# #472: typed custom fields a template declares for its notes. The drawer
# renders an editor per field and stores values on the note's `fields` JSON.
FIELD_TYPES = ("text", "number", "rating", "status", "url", "date", "cost")


def validate_template_fields(fields: list[dict] | None) -> list[dict] | None:
    """Normalise a template's fields declaration; raises ValueError on junk."""
    if fields is None:
        return None
    if not isinstance(fields, list):
        raise ValueError("fields must be a list")
    out = []
    seen = set()
    for f in fields:
        if not isinstance(f, dict) or not f.get("name"):
            raise ValueError("each field needs a name")
        name = str(f["name"]).strip().lower().replace(" ", "_")
        if not name or name in seen:
            raise ValueError(f"field name {name!r} is empty or duplicated")
        seen.add(name)
        ftype = f.get("type") or "text"
        if ftype not in FIELD_TYPES:
            raise ValueError(f"field {name!r}: type must be one of {', '.join(FIELD_TYPES)}")
        entry: dict[str, Any] = {"name": name, "type": ftype}
        if ftype == "status":
            options = [str(o) for o in (f.get("options") or []) if str(o).strip()]
            if not options:
                raise ValueError(f"status field {name!r} needs options")
            entry["options"] = options
        out.append(entry)
    return out

_FILLER_RE = re.compile(r"\b(um+|uh+|er+|ah+|like|you know|i mean|sort of|kind of)\b[,]?\s*", re.IGNORECASE)


def load_templates(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = Path(path or TEMPLATES_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("cannot parse templates file %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_templates(templates: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = Path(path or TEMPLATES_PATH)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(templates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def get_template(name: str, path: Path | None = None) -> dict[str, Any] | None:
    t = load_templates(path).get(name)
    return t if isinstance(t, dict) else None


def apply_output_mode(text: str, mode: str) -> str:
    """Shape raw transcript text for the chosen output mode.

    raw: verbatim. cleaned: filler words stripped, whitespace collapsed,
    first letter capitalised. bullets: one dash per sentence.
    """
    if mode == "raw" or not mode:
        return text
    if mode == "cleaned":
        cleaned = _FILLER_RE.sub("", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
        return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned
    if mode == "bullets":
        parts = [p.strip(" -") for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip(" -")]
        return "\n".join(f"- {p}" for p in parts) if parts else text
    raise ValueError(f"unknown output mode: {mode}")
