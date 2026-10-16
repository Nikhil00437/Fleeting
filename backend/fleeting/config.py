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


VAULT_DIR = Path.home() / "Documents" / "FleetingVault"
CONFIG_DIR = xdg("XDG_CONFIG_HOME", Path.home() / ".config")
DATA_DIR = xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
CONFIG_PATH = CONFIG_DIR / "config.toml"
DB_PATH = DATA_DIR / "fleeting.db"
AUDIO_DIR = DATA_DIR / "audio"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
LOG_PATH = DATA_DIR / "fleeting.log"
# #495: packs and #497: hooks are files, not settings, so they live beside the
# config rather than inside it. Derived from CONFIG_PATH, not CONFIG_DIR: the
# test sandbox redirects CONFIG_PATH, so anything derived from CONFIG_DIR would
# still point at the user's real ~/.config during a test run.
PACKS_DIR = CONFIG_PATH.parent / "packs"
HOOKS_DIR = CONFIG_PATH.parent / "hooks"
# #499: plugins are folders of files, one level like packs and hooks.
PLUGINS_DIR = CONFIG_PATH.parent / "plugins"


def packs_dir() -> Path:
    """Read the module attribute at call time, never a copy taken at import —
    the same rule `PathsConfig.vault_dir` follows, and for the same reason."""
    return Path(PACKS_DIR)


def hooks_dir() -> Path:
    return Path(HOOKS_DIR)


def plugins_dir() -> Path:
    return Path(PLUGINS_DIR)


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 7425

    # #458: a read-only demo, for screenshots, talks and trying the app on
    # someone else's machine. Every mutating `/api` call is refused with a 403
    # naming the mode, rather than succeeding against a database the demo will
    # be judged on.
    #
    # Enforced in middleware, not per-route: a guard every route has to remember
    # to opt into is a guard the next endpoint forgets. The database is seeded
    # on startup only if it is empty, so switching this on over real data does
    # not quietly add a fortnight of fake notes next to your own.
    demo_mode: bool = False

    # #135: lock the app until a passphrase is given. The passphrase is never
    # stored — only a scrypt hash, because a config file that contains the thing
    # it is meant to protect is not a lock.
    lock_enabled: bool = False
    lock_passphrase_hash: str = ""


@dataclass
class PathsConfig:
    # default_factory, not a plain default: a default is evaluated when this
    # class is created, so patching VAULT_DIR later would not reach a Config
    # built afterwards — which is how test notes ended up mirrored into the
    # user's real vault and imported back by the running app.
    vault_dir: str = field(default_factory=lambda: str(VAULT_DIR))
    vault_sync: bool = True
    # #115. `{{year}}` is the default and stays the default: silently
    # relocating five years of notes is not a decision to make on someone's
    # behalf. Supported tokens: year, month, type, first_tag.
    vault_folder_template: str = ""
    # #114. Comma-separated field names, rendered in this order. Empty means the
    # built-in frontmatter only.
    vault_frontmatter_schema: str = ""
    # #117. Empty means off — a `Daily/` folder appearing in a vault that never
    # asked for one is a surprise. Set to "Daily" to enable.
    vault_daily_dir: str = ""


@dataclass
class LLMConfig:
    provider: str = "ollama"  # "ollama" | "lmstudio" | "custom" | "none"
    base_url: str = "http://127.0.0.1:11434"
    model: str = ""
    # #266: comma-separated models tried in order when `model` is unreachable or
    # answers with something unparseable. Empty means no chain — the capture
    # falls back to heuristics on the first failure, as it always did.
    fallback_models: str = ""
    # #92: per-role model overrides. Capture wants a small fast model, reports
    # and the assistant want the big one. Empty means "use `model`", so an
    # untouched config behaves exactly as it did.
    enrich_model: str = ""
    report_model: str = ""
    assistant_model: str = ""
    # #257: comma-separated tags the user already uses. The enricher is told
    # about them and its output is snapped onto them.
    preferred_tags: str = ""
    # #459: capture kinds whose text must never reach a model. Comma-separated,
    # like `preferred_tags`, because hand-editing TOML is how settings get
    # changed and a list of tables would be a worse way to type one.
    never_use_ai_types: str = ""
    # The model used for embeddings, which is very often *not* the chat model:
    # asking a chat model for vectors returns nothing usable. Empty means
    # "use `model`", which preserves every existing config unchanged.
    embedding_model: str = ""
    # Embeddings may live on a different server than chat: a 9B chat model and
    # a 300M embedder are usually not the same process, and one of them is
    # often a desktop app the user closes. Empty means "use base_url", so
    # every existing config is unchanged.
    embedding_base_url: str = ""
    # ...and on a different dialect. The provider picks the request shape as
    # well as the host, and the two are separate decisions: LM Studio serves
    # OpenAI's /v1/embeddings while Ollama serves /api/embeddings. Empty means
    # "use provider".
    embedding_provider: str = ""
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
    # #87: speaker labels via pyannote-audio (optional heavy dep, lazy-imported;
    # pyannote's models are gated on Hugging Face, so this needs a token)
    diarize: bool = False
    hf_token: str = ""
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
    # #110: a nightly "what did I forget?" for open loops. Off by default —
    # an unrequested midnight notification is how an app gets muted, and
    # #416's stale-contact list sets the same precedent.
    nightly_nudge: bool = False


@dataclass
class ActivityConfig:
    enabled: bool = True
    poll_secs: int = 20
    idle_after_min: int = 3
    excluded_apps: str = "zen"  # comma-separated class substrings, e.g. "zen, keepassxc"
    # #66 comma-separated tokens scrubbed out of window titles before they are
    # stored, e.g. "ghp_,sk-or-v1". Emails are always scrubbed regardless.
    redact_patterns: str = ""
    auto_daily_log: bool = True
    # Monday-morning summary of the finished week, on top of the daily report.
    auto_weekly_log: bool = True
    # #454: the directories file-activity scanning is *allowed* to read.
    #
    # Empty by default, and that is the point: the old default scanned
    # ~/Projects, ~/Documents and ~/Downloads without asking. An allow-list that
    # ships full is not an allow-list, it is a default with extra steps. Anything
    # not named here is never scanned, and `GET /api/activity/files/preview`
    # shows what each entry would contribute before you rely on it.
    watch_allowlist: str = ""
    # #335 minutes of silence before a run of sessions becomes a new work
    # block. 10 keeps "read docs, answer a Slack thread" as one block.
    block_gap_min: int = 10
    # #60 where the idle verdict comes from: logind's IdleHint on the user
    # bus, the cursor heuristic, or auto (logind with a cursor fallback).
    idle_source: str = "auto"
    mirror_daily_log: bool = False  # report lives inside the app only, by default
    # Bearer token required on mutating /api requests. Empty = disabled, which
    # keeps the single-user loopback setup working with no extra setup.
    api_token: str = ""
    # #142: require the token for *reads* too, not just writes.
    #
    # Off by default, and that is a real constraint rather than caution: the
    # browser SPA is served from the same origin, so it cannot hold a secret it
    # then sends to that origin — anything in the page is readable by the page.
    # The Origin guard is what protects the browser case; this protects the case
    # of another local process reading your notes with curl. Turn it on when the
    # scripts are your own clients and the browser tab is not the concern.
    reads_require_token: bool = False
    # Days of window-activity history to keep. Older rows are pruned on boot;
    # daily reports only ever look back 24h.
    retention_days: int = 30


@dataclass
class ThemeConfig:
    """#495. Which pack is active, if any. The tokens themselves stay in the pack
    file rather than being copied into config.toml, so re-applying an updated
    pack is one click instead of a merge."""

    active: str = ""


@dataclass
class LoggingConfig:
    """#389.

    `level` was a hardcoded `logging.INFO` that no config could change, which
    is the opposite of what a log level is for.

    `log_format` defaults to text because this is a local app and the person
    reading the log is usually its owner, tailing it. JSON is there for #395's
    diagnostics bundle, which has to filter errors out of a log rather than
    grep prose — not because JSON is better in the abstract.

    `max_bytes` exists because the user's log had reached 6.2 MB and grew
    without bound. 0 disables rotation, for anyone who wants the whole history.
    """

    level: str = "INFO"
    log_format: str = "text"  # "text" | "json"
    max_bytes: int = 2_000_000
    backups: int = 3


@dataclass
class ExperimentalConfig:
    """#195: endpoints that shipped before anything was built to reach them.

    Not a flag *framework* — config.toml already has per-section toggles
    (`[llm] provider`, `[activity] enabled`, `[paths] vault_sync`) and a second
    system for the same job is worse than none. What was missing was one
    consistent gate for endpoints that exist and are unreachable from the UI.

    All off by default. An endpoint with nothing wired to it should not be
    silently live in someone's install; opting in is one line of config.

    This is for taste, not access control. These routes inherit the host guard,
    the bearer token and the origin check like every other `/api` route —
    turning one off must never be what keeps someone out.
    """

    tone: bool = False  # GET /api/notes/tone — #259 urgency/sentiment ordering
    benchmark: bool = False  # POST /api/benchmark/run — #264 model scoring
    pinned_context: bool = False  # #101 notes pinned into an assistant thread
    # #295: runs a read-only SELECT against the real database. Off by
    # default because it is the most powerful thing in the app; the
    # sandbox is two independent guards, not one.
    sql_console: bool = False


@dataclass
class NotesConfig:
    # #274: notes sit in the trash this long before the boot purge hard-deletes
    # them. 0 disables the purge entirely (trash grows forever).
    trash_retention_days: int = 30
    # #138: how long each capture source stays in the database at all, as
    # `"youtube:7, file:30"` — days, keyed on `notes.type`. Empty means no
    # per-source ageing, which is the safe direction: a policy that quietly
    # applied to everything would age out the notes you wrote in favour of the
    # ones you were dictated.
    #
    # Retention *trashes*; `trash_retention_days` above is what makes it final.
    # Both stages matter — the first is the recoverable one.
    retention_by_source: str = ""
    # #99: encrypt the *content* of notes marked sensitive, key in the keyring.
    # Off by default: turning it on does not rewrite what is already stored, so
    # existing plaintext keeps reading back unchanged.
    encrypt_sensitive: bool = False


@dataclass
class TasksConfig:
    # #32/#442: the day-load bar and the weekly planner divide planned task
    # estimates by this budget. Focus hours, not clock hours.
    daily_capacity_min: int = 240
    # #443: IANA zone for "today". Empty = the machine's local zone.
    timezone: str = ""
    # #444: extra non-working days as YYYY-MM-DD, comma-separated. Weekends
    # are already excluded; this is for public holidays that should not break
    # streaks or fill the planner.
    holidays: str = ""


@dataclass
class WritingConfig:
    # #451: a house style applied to every rewrite and title suggestion. Free
    # text because it is the user's own words, and a rule the app cannot
    # enumerate ("no semicolons", "British spelling") is the common case.
    style_guide: str = ""


@dataclass
class EntitiesConfig:
    # #416: days without a mention before a contact is "stale". 0 disables the
    # list entirely — the idea says opt-in, and an unwanted one is noise.
    stale_days: int = 0


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    transcribe: TranscribeConfig = field(default_factory=TranscribeConfig)
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    activity: ActivityConfig = field(default_factory=ActivityConfig)
    notes: NotesConfig = field(default_factory=NotesConfig)
    experimental: ExperimentalConfig = field(default_factory=ExperimentalConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    entities: EntitiesConfig = field(default_factory=EntitiesConfig)
    writing: WritingConfig = field(default_factory=WritingConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# Sections that map to dataclass fields, used for (de)serialization.
_SECTIONS: dict[str, type] = {
    "server": ServerConfig,
    "paths": PathsConfig,
    "llm": LLMConfig,
    "transcribe": TranscribeConfig,
    "youtube": YouTubeConfig,
    "notifications": NotificationsConfig,
    "activity": ActivityConfig,
    "notes": NotesConfig,
    "experimental": ExperimentalConfig,
    "logging": LoggingConfig,
    "tasks": TasksConfig,
    "entities": EntitiesConfig,
    "writing": WritingConfig,
    "theme": ThemeConfig,
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
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def expand_path(raw: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(raw)))
