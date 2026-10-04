"""Path & configuration management.

Config lives at ~/.config/fleeting/config.toml, mutable both by hand and via
the settings API. Everything defaults to locations under the user's XDG dirs
so the app is self-contained and trivially portable/back-uppable.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

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
    watch_dirs: str = "~/Projects, ~/Documents, ~/Downloads"
    mirror_daily_log: bool = False  # report lives inside the app only, by default


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


def _coerce(value, target_type):
    """Coerce a TOML/JSON value to the field's type where sensible."""
    if target_type is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if target_type is int:
        return int(value)
    return value


def load_config() -> Config:
    cfg = Config()
    if not CONFIG_PATH.exists():
        save_config(cfg)
        return cfg
    try:
        raw = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("failed to parse %s, using defaults", CONFIG_PATH)
        return cfg
    for section_name, section_type in _SECTIONS.items():
        data = raw.get(section_name, {})
        section = getattr(cfg, section_name)
        for f in fields(section_type):
            if f.name in data:
                try:
                    setattr(section, f.name, _coerce(data[f.name], f.type))
                except (TypeError, ValueError):
                    log.warning("invalid value for %s.%s: %r", section_name, f.name, data[f.name])
    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for section_name, section_type in _SECTIONS.items():
        section = getattr(cfg, section_name)
        lines.append(f"[{section_name}]")
        for f in fields(section_type):
            val = getattr(section, f.name)
            if isinstance(val, bool):
                lines.append(f"{f.name} = {'true' if val else 'false'}")
            elif isinstance(val, str):
                escaped = val.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'{f.name} = "{escaped}"')
            else:
                lines.append(f"{f.name} = {val}")
        lines.append("")
    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))
