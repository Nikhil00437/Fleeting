"""#139: secrets in the OS keyring rather than plaintext in config.toml.

Three secrets live in the config today — `llm.api_key`, `transcribe.hf_token`,
`activity.api_token` — and config.toml is world-readable by default in most
installs, gets copied into dotfile repos, and ends up in backups. This moves them
behind an interface with a real keyring on the platforms that have one, and an
honest fallback where none is.

**The fallback is not a silent downgrade.** `keyring_available()` is reported by
`GET /api/keyring`, and the stored location is recorded, so "my key is in a file
next to the config" is a fact the user can see rather than a surprise they
discover by reading the source. A file fallback is `0600` in the user's own
config directory, which is not the same as plaintext in a world-readable file —
but it is worse than a real keyring and the API says so.

**The value stays in config.toml, as a marker, never as a secret.** `api_key` in
the file means "there is a key stored under `llm.api_key`". That keeps the config
diffable and greppable, keeps a config file portable, and means a leaked
`config.toml` reveals that a key exists rather than what it is.

Deleting the key from the keyring is supported and tested, because "clear my API
key" is a thing people need to do and it is easy to leave a secret behind.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("fleeting.keyring")

SERVICE = "fleeting"

# What config.toml holds in place of a secret. Its only job is to make the file
# self-describing: "a key is stored" rather than an empty string that reads as
# "no key configured" and sends someone hunting for a setting they already set.
KEYRING_MARKER = "<stored in keyring>"


@dataclass(frozen=True)
class Backend:
    """Where secrets actually live, and whether that is good enough."""

    name: str
    available: bool
    detail: str
    secure: bool


def _secret_tool() -> str | None:
    return shutil.which("secret-tool")


def _backend() -> Backend:
    """Pick the best available store.

    `secret-tool` is the freedesktop Secret Service, which is what GNOME, KDE and
    most Linux desktops actually implement. Windows and macOS get the same
    interface through `keyring`, if the user has it installed.
    """
    if _secret_tool():
        return Backend("secret-service", True, "the desktop Secret Service", True)
    if shutil.which("keyring"):
        return Backend("keyring-cli", True, "the `keyring` CLI", True)
    return Backend(
        "file",
        True,
        f"no OS keyring found — falling back to a 0600 file at {Path(_fallback_path()).parent}",
        False,
    )


def backend() -> Backend:
    return _backend()


def _fallback_path() -> Path:
    from ..config import CONFIG_DIR

    return Path(CONFIG_DIR) / "secrets.json"


def _read_fallback() -> dict[str, Any]:
    try:
        return json.loads(_fallback_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_fallback(data: dict[str, Any]) -> None:
    path = _fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    # 0600 before the content is written, not after: a file created with the
    # default mode has a window where it is world-readable.
    os.chmod(path, 0o600)


def _keyring_get(name: str) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [_secret_tool(), "lookup", "service", SERVICE, "username", name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("keyring lookup for %s failed: %s", name, exc)
        return None


def _keyring_set(name: str, value: str) -> bool:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                _secret_tool(),
                "store",
                "--label=fleeting",
                f"service={SERVICE}",
                f"username={name}",
            ],
            input=value,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("keyring store for %s failed: %s", name, exc)
        return False


def _keyring_delete(name: str) -> bool:
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [_secret_tool(), "clear", "service", SERVICE, "username", name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def get(name: str) -> str | None:
    """One secret, or None. Never raises — a missing key is an answer."""
    be = _backend()
    if be.name in ("secret-service", "keyring-cli") and _secret_tool():
        return _keyring_get(name)
    if be.name == "keyring-cli":
        try:
            out = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["keyring", "get", SERVICE, name],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            return out.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    value = _read_fallback().get(name)
    return str(value) if value else None


def set_secret(name: str, value: str) -> bool:
    """Store it. Returns whether the secure backend took it."""
    if _secret_tool():
        if _keyring_set(name, value):
            return True
        log.warning("secret-tool refused %s — falling back to the file store", name)
    _write_fallback({**_read_fallback(), name: value})
    return False


def delete_secret(name: str) -> bool:
    """Remove it from wherever it is.

    Both stores are cleared even when only one holds it: a secret left behind in
    the file after someone deleted it from the keyring is exactly the thing this
    feature exists to prevent.
    """
    ok = True
    if _secret_tool():
        ok = _keyring_delete(name) and ok
    data = _read_fallback()
    if name in data:
        del data[name]
        _write_fallback(data)
    return ok


def status() -> dict[str, Any]:
    """What the Settings page shows, and what a test asserts against."""
    be = _backend()
    return {
        "backend": be.name,
        "available": be.available,
        "secure": be.secure,
        "detail": be.detail,
        "stored": sorted(_read_fallback().keys()),
        "fallback_path": str(_fallback_path()) if not be.secure else "",
    }

def resolve(name: str, configured: str) -> str:
    """The secret to actually use, given what config.toml holds.

    The keyring wins when it has the name; otherwise `configured` is returned so
    a key written into the config *before* this feature — or on a machine with no
    keyring — keeps working. The marker is never returned as a credential: a
    literal "<stored in keyring>" sent as a bearer token 401s, and the failure
    looks like a bad key rather than a missing lookup.
    """
    stored = get(name)
    if stored:
        return stored
    return "" if configured.strip() == KEYRING_MARKER else configured
