"""#495: theme and prompt packs, installed offline from a folder.

A pack is one JSON file:

    {"name": "Zettel", "description": "...", "version": 1,
     "theme": {"--ink-100": "#f0f0f0"},
     "prompts": {"style_guide": "...", "preferred_tags": "..."}}

"Offline-friendly" is the requirement and also the threat model: a pack is a
file someone drops into a folder from a USB stick, a friend, or a directory of
four hundred half-finished experiments. Nothing here reaches the network, and
nothing here raises on bad input — every failure returns a reason next to the
packs that did load, because a marketplace format nobody trusts is a format
nobody uses.

Two gates, because a pack is untrusted input:

- `theme` keys must be CSS custom properties (`--name`) and values must be
  simple. A token value containing `}` can close the rule it lives in and
  redefine the rest of the sheet.
- `prompts` keys must be in `PROMPT_TARGETS`. A pack that could set arbitrary
  config fields could point your vault somewhere else entirely.

Active theme lives in config as a name; the tokens stay in the pack file. So
updating a pack is one click rather than a merge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from ..config import Config, packs_dir

# Packs shipped in the repo, so there is something to install on a fresh clone.
# None when installed as a package with no repo alongside — `search_dirs`
# drops it rather than reporting a folder that does not exist.
BUNDLED_DIR = Path(__file__).resolve().parents[3] / "packs"

# CSS custom property: --name, no spaces, no braces.
_TOKEN_NAME = re.compile(r"^--[a-zA-Z0-9_-]+$")

# Values a browser accepts inside a custom property without ending the rule.
# Deliberately strict: a `;` or a `}` lets a pack rewrite more than its token,
# and `url(`/`expression(` reach out of the stylesheet.
_TOKEN_VALUE = re.compile(r"^[#a-zA-Z0-9 ,.%()_/+\-]*$")

# The only config a pack may write. A whitelist rather than a schema: an unknown
# key is dropped silently, because packs are written by hand and one extra key
# should not make the whole pack unusable.
PROMPT_TARGETS = ("style_guide", "preferred_tags")


def _apply_prompts(cfg: Config, prompts: dict[str, Any]) -> list[str]:
    """Set only known keys, and only to a non-empty string.

    An absent key leaves the current value alone: a theme-only pack must not
    blank a style guide someone spent time writing.
    """
    applied: list[str] = []
    for key, value in prompts.items():
        if key == "style_guide":
            cfg.writing.style_guide = value
        elif key == "preferred_tags":
            cfg.llm.preferred_tags = value
        applied.append(key)
    return applied


def _clean_theme(raw: Any) -> dict[str, str]:
    """Keep only well-formed `--name: value` pairs. See the module docstring."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not _TOKEN_NAME.match(name):
            continue
        if not isinstance(value, str) or not _TOKEN_VALUE.match(value.strip()):
            continue
        out[name] = value.strip()
    return out


def _clean_prompts(raw: Any) -> dict[str, str]:
    """Only the whitelisted keys, and only non-empty strings.

    Filtered here rather than at install time so the list shows exactly what
    would be applied — echoing a key back that install then silently ignores is
    how someone ends up wondering why their `vault_dir` never changed.
    """
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k, v in raw.items()
        if k in PROMPT_TARGETS and isinstance(v, str) and v.strip()
    }


def _pack_from(payload: dict[str, Any], fallback: str, active: str) -> dict[str, Any]:
    """One pack as the API serves it.

    The name falls back to the file stem so a hand-written pack with only a
    `theme` key is still listable and installable — otherwise it is invisible
    until someone discovers the format requires a name nobody mentioned.
    """
    name = payload.get("name")
    name = name.strip() if isinstance(name, str) and name.strip() else fallback
    description = payload.get("description")
    return {
        "name": name,
        "description": description.strip() if isinstance(description, str) else "",
        "theme": _clean_theme(payload.get("theme")),
        "prompts": _clean_prompts(payload.get("prompts")),
        "active": name == active or fallback == active,
    }


def load_packs(directory: Path, cfg: Config) -> tuple[list[dict[str, Any]], list[str]]:
    """Every readable pack in `directory`, plus a reason per unreadable one.

    Non-`.json` files are ignored silently — the folder is the user's and may
    hold notes. A `.json` that fails to parse is reported, because that is a
    pack someone meant to install.
    """
    packs: list[dict[str, Any]] = []
    errors: list[str] = []
    active = (cfg.theme.active or "").strip()
    try:
        files = sorted(Path(directory).glob("*.json"))
    except OSError:
        return packs, errors
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name}: not a JSON object")
            continue
        packs.append(_pack_from(payload, path.stem, active))
    packs.sort(key=lambda p: p["name"].lower())
    return packs, errors


def list_packs(directory: Path, cfg: Config) -> list[dict[str, Any]]:
    return load_packs(directory, cfg)[0]


def install_pack(
    directories: "Path | list[Path]", name: str, cfg: Config, save: Callable[[Config], None]
) -> dict[str, Any]:
    """Apply a pack's theme and prompts, then persist.

    Tokens are not copied into config.toml — only the active name is, so an
    updated pack is re-applied by installing again rather than by merging two
    half-stale copies of its colours.

    Takes one folder or a search order, so the router can hand it
    `search_dirs()` without this function caring where the pack came from.
    """
    dirs = [directories] if isinstance(directories, Path) else list(directories)
    packs, _ = load_pack_set(dirs, cfg)
    match = next(
        (p for p in packs if p["name"] == name or any(_stem_for(d, name) == name for d in dirs)),
        None,
    )
    if match is None:
        raise KeyError(name)
    cfg.theme.active = match["name"]
    _apply_prompts(cfg, match["prompts"])
    save(cfg)
    return match


def _stem_for(directory: Path, name: str) -> str:
    """A pack's filename stem, so `/api/packs/<stem>/install` works for a pack
    that declares no `name` of its own."""
    return name if (Path(directory) / f"{name}.json").exists() else "\0no-such-pack\0"

def search_dirs(directory: Path | None = None) -> list[Path]:
    """Where to look: the user's folder first, then the bundled one.

    Order matters — `load_pack_set` lets the first folder win on a name clash,
    so editing a bundled pack by dropping your own copy into
    `~/.config/fleeting/packs/` is the supported way to change one.
    """
    dirs = [Path(directory) if directory is not None else packs_dir()]
    if BUNDLED_DIR.is_dir():
        dirs.append(BUNDLED_DIR)
    return dirs


def load_pack_set(directories: list[Path], cfg: Config) -> tuple[list[dict[str, Any]], list[str]]:
    """`load_packs` across several folders, first folder winning on a clash."""
    packs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for directory in directories:
        found, problems = load_packs(directory, cfg)
        errors.extend(problems)
        for pack in found:
            if pack["name"] in seen:
                continue
            seen.add(pack["name"])
            packs.append(pack)
    packs.sort(key=lambda p: p["name"].lower())
    return packs, errors
