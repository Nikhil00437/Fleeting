"""Per-app dictation profiles (#428).

Map an active-window class (e.g. "firefox", "Code") to the capture settings
that make sense there: language, template, output mode. Stored as JSON next
to config.toml — same rationale as templates.json.

  {
    "firefox": { "language": "en", "mode": "cleaned" },
    "slack":   { "language": "en", "template": "meeting", "mode": "bullets" }
  }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR

log = logging.getLogger("fleeting.profiles")

PROFILES_PATH = CONFIG_DIR / "profiles.json"


def load_profiles(path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = Path(path or PROFILES_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("cannot parse profiles file %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_profiles(profiles: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    path = Path(path or PROFILES_PATH)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(profiles, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def match_profile(app_class: str | None, path: Path | None = None) -> dict[str, Any] | None:
    """Case-insensitive substring match: the window class contains the key."""
    if not app_class:
        return None
    hay = app_class.lower()
    for key, profile in load_profiles(path).items():
        if key.lower() in hay and isinstance(profile, dict):
            return dict(profile)
    return None
