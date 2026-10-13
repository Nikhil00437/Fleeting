"""#499: the plugin manifest — a catalogue of what an extension provides.

A plugin is a folder under `~/.config/fleeting/plugins/` containing
`plugin.json`. The manifest declares capture sources, enrichers and views, and
for each one names the **hook** that implements it.

That division is the entire design. #497 already runs hooks and #496 runs
commands, so execution exists and is opt-in, per-file, in a directory the user
controls. A manifest describes; it does not execute. That is what makes a plugin
shareable: a folder you were sent is data, not code, and the only thing it can
name is a hook that already has to be installed separately by the user.

Which is why `_ALLOWED` drops anything resembling a command. If `plugin.json`
could carry `"command": "curl … | sh"`, every other check here would be a
comfort blanket over remote code execution, and the "untrusted input" reasoning
in `packs.py` would not apply.

This format is versioned by `api_version`, and a manifest asking for a newer one
is rejected *with the number*, because "incompatible" tells someone nothing and
"this app supports 1, the plugin wants 2" tells them what to do.

Nothing raises. A plugin folder is somebody's work; one typo must not cost them
the listing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Config, plugins_dir

# Bump when the shape below changes in a way an existing manifest would not
# survive. A plugin declaring a higher number is rejected with both numbers.
API_VERSION = 1

_REQUIRED = ("name", "version", "api_version", "provides")

# What each kind of entry may carry. Everything else is dropped.
_PROVIDES: dict[str, tuple[str, ...]] = {
    # a source is a labelled way to put something in; `hook` is the hook that
    # handles what it produces
    "capture_sources": ("name", "title", "description", "hook"),
    # an enricher is a hook that runs on a note
    "enrichers": ("name", "description", "hook"),
    # a view is something the UI can link to
    "views": ("name", "title", "description", "url"),
}

# Fields that would turn data into an execution vector. Dropped wherever they
# appear — this list is the security property, and `tests/test_plugins.py`
# asserts it.
_NEVER = ("command", "script", "exec", "shell", "argv", "entry", "module", "code")


def _clean_entry(kind: str, raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """One entry of one `provides` list, or an error saying what is wrong."""
    allowed = _PROVIDES[kind]
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"{kind}: each entry must be an object"]
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, [f"{kind}: an entry has no `name`"]
    out: dict[str, Any] = {"name": name.strip()}
    for key in allowed:
        if key == "name" or key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str) or not value.strip():
            continue
        # A hook is a *name*, resolved by the user installing it. Keeping a
        # traversal out of it costs nothing and means the string stays safe to
        # use as an identifier wherever it is later joined to a path.
        if key == "hook" and (".." in value or value.startswith("/")):
            errors.append(f"{kind} {name}: hook must be a bare filename, not {value!r}")
            continue
        out[key] = value.strip()
    return out, errors


def validate(payload: Any) -> list[str]:
    """Everything wrong with a manifest, in words a human can act on."""
    if not isinstance(payload, dict):
        return ["manifest is not a JSON object"]
    errors: list[str] = []
    for key in _REQUIRED:
        if key not in payload:
            errors.append(f"missing `{key}`")
    name = payload.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        errors.append("`name` must be a non-empty string")
    version = payload.get("version")
    if version is not None and not isinstance(version, str):
        errors.append("`version` must be a string, e.g. \"0.1.0\"")
    api = payload.get("api_version")
    if api is not None:
        if not isinstance(api, int) or isinstance(api, bool):
            errors.append("`api_version` must be an integer")
        elif api > API_VERSION:
            # Both numbers, always. "Incompatible" is the least useful thing a
            # loader can say to someone who just wrote their first plugin.
            errors.append(
                f"`api_version` {api} is newer than this app supports ({API_VERSION}) — update Fleeting"
            )
    provides = payload.get("provides")
    if provides is not None:
        if not isinstance(provides, dict):
            errors.append("`provides` must be an object keyed by kind")
        else:
            for kind, value in provides.items():
                # An unknown kind is ignored, not an error: a plugin built for a
                # future app should still load and show what this one
                # understands.
                if kind not in _PROVIDES:
                    continue
                if not isinstance(value, list):
                    errors.append(f"provides.{kind} must be a list")
                    continue
                for raw in value:
                    _entry, entry_errors = _clean_entry(kind, raw)
                    errors.extend(entry_errors)
    return errors


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    """The manifest as the API serves it: known fields only.

    `_NEVER` is not consulted here on purpose — it is enforced by
    `_clean_entry`, which only copies keys from `_PROVIDES`. That is a whitelist
    rather than a denylist, so a field nobody thought of is dropped by default
    instead of being one more thing to remember to block.
    """
    provides: dict[str, list[dict[str, Any]]] = {}
    raw_provides = payload.get("provides")
    if isinstance(raw_provides, dict):
        for kind, value in raw_provides.items():
            if kind not in _PROVIDES or not isinstance(value, list):
                continue
            entries = [e for e in (_clean_entry(kind, r)[0] for r in value) if e]
            if entries:
                provides[kind] = entries
    out: dict[str, Any] = {
        "name": payload.get("name"),
        "version": payload.get("version"),
        "api_version": payload.get("api_version"),
        "provides": provides,
    }
    for key in ("description", "author", "homepage"):
        if isinstance(payload.get(key), str):
            out[key] = payload[key]
    return out


def discover(directory: Path, cfg: Config) -> list[dict[str, Any]]:
    return load_plugins(directory, cfg)[0]


def load_plugins(directory: Path, cfg: Config) -> tuple[list[dict[str, Any]], list[str]]:
    """Every valid plugin, plus a reason per one that is not."""
    plugins: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        folders = sorted(p for p in Path(directory).iterdir() if p.is_dir())
    except OSError:
        return plugins, errors
    for folder in folders:
        path = folder / "plugin.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{folder.name}: {exc}")
            continue
        problems = validate(payload)
        if problems:
            errors.extend(f"{folder.name}: {p}" for p in problems)
            continue
        plugin = _clean(payload)
        plugin["folder"] = folder.name
        plugins.append(plugin)
    plugins.sort(key=lambda p: str(p.get("name") or "").lower())
    return plugins, errors


def search_dirs(directory: Path | None = None) -> list[Path]:
    """The user's plugins folder, then the ones shipped in the repo."""
    dirs = [Path(directory) if directory is not None else plugins_dir()]
    bundled = Path(__file__).resolve().parents[3] / "plugins"
    if bundled.is_dir() and bundled not in dirs:
        dirs.append(bundled)
    return dirs