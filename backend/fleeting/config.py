"""Path & configuration management.

Config lives at ~/.config/fleeting/config.toml, mutable both by hand and via
the settings API. Everything defaults to locations under the user's XDG dirs
so the app is self-contained and trivially portable/back-uppable.
"""

from __future__ import annotations

import logging
import os
import secrets
import tomllib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path
from typing import Any, get_type_hints

log = logging.getLogger("fleeting.config")

APP_NAME = "fleeting"


def xdg(env_var: str, fallback: Path) -> Path:
    base = os.environ.get(env_var)
    if base:
        first = Path(base.split(":")[0])
        return first / APP_NAME
    return fallback / APP_NAME


CONFIG_DIR = xdg("XDG_CONFIG_HOME", Path.home() / ".config")
DATA_DIR = xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
CONFIG_PATH = CONFIG_DIR / "config.toml"
DB_PATH = DATA_DIR / "fleeting.db"
AUDIO_DIR = DATA_DIR / "audio"
LOG_PATH = DATA_DIR / "fleeting.log"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 7425


@dataclass
class PathsConfig:
    vault_dir: str = str(Path.home() / "Documents" / "FleetingVault")
    vault_sync: bool = True


@dataclass
class LLMConfig:
    provider: str = "ollama"  # "ollama" | "lmstudio" | "custom" | "none"
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    timeout_secs: int = 120
    # Bearer token for OpenAI-compatible endpoints. Stored in plaintext in
    # ~/.config/fleeting/config.toml, so keep that file readable only by you.
    api_key: str = ""


@dataclass
class TranscribeConfig:
    model: str = "base"  # tiny | base | small | medium
    language: str = "auto"  # "auto" or ISO-639-1 code
    # #89: names/terms whisper should expect, passed as initial_prompt
    vocabulary: str = ""
    # #90: whisper's task="translate" targets English; auto-detection
    # already happens per memo when language is "auto"
    translate: bool = False
    # #91: loudness-normalise before transcription, and keep raw audio?
    cleanup_audio: bool = False
    keep_audio: bool = True
    # #429: spoken punctuation commands ("comma" -> ",", "new line" -> "\n")
    voice_punctuation: bool = False
    # #434: sentence-case the transcript and capitalise bare "i"
    auto_format: bool = False
    # #432: "spoken phrase=written form" pairs, comma-separated
    replacements: str = ""


@dataclass
class YouTubeConfig:
    transcribe_fallback: bool = True
    max_duration_min: int = 45


@dataclass
class NotificationsConfig:
    desktop: bool = True


@dataclass
class ActivityConfig:
    enabled: bool = True
    poll_secs: int = 20
    idle_after_min: int = 3
    excluded_apps: str = "zen"  # comma-separated class substrings, e.g. "zen, keepassxc"
    auto_daily_log: bool = True
    # Monday-morning summary of the finished week, on top of the daily report.
    auto_weekly_log: bool = True
    watch_dirs: str = "~/Projects, ~/Documents, ~/Downloads"
    mirror_daily_log: bool = False  # report lives inside the app only, by default
    # Bearer token required on mutating /api requests. Empty = disabled, which
    # keeps the single-user loopback setup working with no extra setup.
    api_token: str = ""
    # Days of window-activity history to keep. Older rows are pruned on boot;
    # daily reports only ever look back 24h.
    retention_days: int = 30


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    activity: ActivityConfig = field(default_factory=ActivityConfig)


# Sections that map to dataclass fields, used for (de)serialization.
_SECTIONS: dict[str, type] = {
    "server": ServerConfig,
    "paths": PathsConfig,
    "llm": LLMConfig,
    "transcribe": TranscribeConfig,
    "youtube": YouTubeConfig,
    "notifications": NotificationsConfig,
    "activity": ActivityConfig,
}


def _coerce(value: Any, target_type: Any) -> Any:
    """Coerce a TOML value to the field's type. Raises ValueError if it can't."""
    if target_type is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if target_type is int:
        if isinstance(value, bool):  # TOML has no int type; bool is not one
            raise ValueError(f"expected int, got bool {value!r}")
        return int(value)
    return value


# Resolved once per section: under `from __future__ import annotations` a field's
# `.type` is the *string* "int", so `_coerce`'s `is int` check never matches.
_FIELD_TYPES: dict[str, dict[str, Any]] = {
    name: get_type_hints(cls) for name, cls in _SECTIONS.items()
}


def load_config() -> Config:
    """Load config, degrading per-value rather than resetting everything.

    A hand-edited file is the documented workflow, so a typo in one value must
    not discard the rest of the user's settings.
    """
    cfg = Config()
    if not CONFIG_PATH.exists():
        save_config(cfg)
        return cfg
    try:
        raw = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        # Never overwrite a file we could not read — that would destroy the
        # user's settings with no way back.
        log.error("cannot parse %s, keeping existing config: %s", CONFIG_PATH, exc)
        return cfg
    for section_name, section_type in _SECTIONS.items():
        data = raw.get(section_name, {})
        if not isinstance(data, dict):
            log.warning("%s is not a table, ignoring", section_name)
            continue
        section = getattr(cfg, section_name)
        hints = _FIELD_TYPES[section_name]
        for f in fields(section_type):
            if f.name not in data:
                continue
            default = f.default if f.default is not MISSING else f.default_factory()
            try:
                setattr(section, f.name, _coerce(data[f.name], hints.get(f.name, str)))
            except (TypeError, ValueError):
                log.warning(
                    "invalid %s.%s = %r, keeping default %r",
                    section_name, f.name, data[f.name], default,
                )
                setattr(section, f.name, default)
    return cfg


def _toml_str(value: str) -> str:
    """Escape a string for a TOML basic string.

    Newlines and control chars MUST be escaped — an unescaped newline silently
    produces a file that no longer parses, and the old code then reset every
    setting on next boot.
    """
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _load_raw() -> dict[str, Any]:
    """Parse the config file without applying it. Empty dict if unusable."""
    try:
        return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("cannot re-read %s for comment preservation: %s", CONFIG_PATH, exc)
        return {}


def save_config(cfg: Config) -> None:
    """Write config atomically, preserving comments and unknown keys.

    Atomic because a crash mid-write would otherwise truncate the file and lose
    every setting; comment-preserving because the file is documented as
    hand-editable, so hand-added keys and notes should survive a settings save.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    previous = _load_raw()
    lines: list[str] = []
    for section_name, section_type in _SECTIONS.items():
        section = getattr(cfg, section_name)
        old = previous.get(section_name)
        old = old if isinstance(old, dict) else {}
        lines.append(f"[{section_name}]")
        for f in fields(section_type):
            val = getattr(section, f.name)
            if isinstance(val, bool):
                lines.append(f"{f.name} = {'true' if val else 'false'}")
            elif isinstance(val, str):
                lines.append(f"{f.name} = {_toml_str(val)}")
            else:
                lines.append(f"{f.name} = {val}")
        for key, val in old.items():
            if key not in {f.name for f in fields(section_type)}:
                lines.append(f"{key} = {_toml_val(val)}")
        lines.append("")
    text = "\n".join(lines)

    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)  # atomic within the same filesystem
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _toml_val(val: Any) -> str:
    """Serialize an arbitrary TOML value from a hand-edited file."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        return _toml_str(val)
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return "[" + ", ".join(_toml_val(v) for v in val) + "]"
    if isinstance(val, dict):
        inner = ", ".join(f"{k} = {_toml_val(v)}" for k, v in val.items())
        return "{" + inner + "}"
    return _toml_str(str(val))


def ensure_token(cfg: Config) -> str:
    """Return the API token, generating and persisting one on first run.

    Loopback binding is not an auth boundary: any local process can reach the
    port. An unguessable token is the cheapest thing that actually stops it.
    Existing tokens are never rotated — that would break a running client.
    """
    existing = cfg.activity.api_token.strip()
    if existing:
        return existing

    # Re-read before minting: if a previous run generated a token but failed to
    # persist it, minting a second one would lock out a live client.
    try:
        on_disk = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        stored = str(on_disk.get("activity", {}).get("api_token") or "").strip()
    except (OSError, tomllib.TOMLDecodeError):
        stored = ""
    if stored:
        cfg.activity.api_token = stored
        return stored

    token = secrets.token_urlsafe(32)
    cfg.activity.api_token = token
    try:
        save_config(cfg)
    except OSError:
        log.warning("could not persist generated API token", exc_info=True)
    return token


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))
