"""#100: say what is missing before someone wonders why nothing works.

Every one of these has been found the hard way during development: ffmpeg
missing means voice memos fail with a conversion error, yt-dlp missing means
YouTube captures silently do nothing, a missing `hyprctl` means the timeline is
permanently empty with nothing to say why.

The probes are injectable so the tests do not describe *this* machine. A test
that asserts ffmpeg is installed passes here and on any dev box and fails in CI
— worse than no test, because it trains you to re-run instead of read.

What this deliberately is not: a "pick a model" flow or an Obsidian importer.
Both already exist — `[llm].enrich_model` and friends in Settings → AI, and the
vault watcher traverses `vault_dir` recursively for `.md`, which is what an
Obsidian vault already is. Building either would duplicate working code.

Required-ness is a judgement about what the app *is*: the vault is the only
mandatory thing, because without it captures have nowhere to go. A missing
ffmpeg degrades one feature. Reporting those as failures trains people to
ignore the panel, which is the opposite of the point.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Ollama's default; only used when the config leaves base_url empty.
_DEFAULT_BASE = {"ollama": "http://127.0.0.1:11434", "lmstudio": "http://127.0.0.1:1234"}


def _default_run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _default_http(url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback only
            return _json_dict(resp.read())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _json_dict(raw: bytes) -> dict | None:
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _default_writable(path: str) -> bool:
    """Walk up to the nearest existing ancestor: asking about a directory that
    does not exist yet is a normal state during onboarding."""
    if not path:
        return True
    probe = Path(path)
    while not probe.is_dir():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return os.access(probe, os.W_OK)


@dataclass(frozen=True)
class Probe:
    """Everything this module needs from the outside world.

    The defaults are the real thing, so `check_all()` with no arguments is a
    live check; tests override what they care about and get a machine where
    nothing exists.
    """

    which: Callable[[str], str | None] = shutil.which
    run: Callable[..., tuple[int, str, str]] = _default_run
    http: Callable[..., dict | None] = _default_http
    writable: Callable[[str], bool] = _default_writable
    vault_dir: str = ""
    note_count: int = 0
    config: Any = None


def _check(name: str, ok: bool, required: bool, detail: str, fix: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "required": required,
        "detail": detail,
        "fix": "" if ok else fix,
    }


def _binary(probe: Probe, name: str, fix: str, args: list[str]) -> dict[str, Any]:
    """`which` is not enough: a stale PATH entry can point at a file that
    cannot execute, which is exactly the case that wastes an afternoon.

    `args` is the version form each tool actually accepts, which is not one
    shape: ffmpeg 9 exits 8 on `--version` and 0 on `-version`, and hyprctl
    wants the `version` subcommand. Probing with the wrong form reports a
    working tool as broken.
    """
    try:
        path = probe.which(name)
    except Exception:  # noqa: BLE001 - a broken probe must not lose the panel
        path = None
    if not path:
        return _check(name, False, False, "not on PATH", fix)
    code, out, _ = probe.run([path, *args], 5.0)
    if code != 0:
        return _check(name, False, False, f"found at {path} but exits {code}", fix)
    first = out.strip().splitlines()[0] if out.strip() else path
    return _check(name, True, False, first, "")


def _model_names(payload: dict | None) -> list[str] | None:
    """Normalise Ollama's `models[].name` and OpenAI-shaped `data[].id`."""
    if not payload:
        return None
    if isinstance(payload.get("models"), list):
        return [str(m.get("name") or m.get("model") or "") for m in payload["models"]]
    if isinstance(payload.get("data"), list):
        return [str(m.get("id") or "") for m in payload["data"]]
    return None


def _check_llm(probe: Probe) -> dict[str, Any]:
    cfg = getattr(probe.config, "llm", None)
    provider = str(getattr(cfg, "provider", "none") or "none")
    if provider == "none":
        return _check(
            "llm",
            False,
            False,
            "no model configured — heuristics handle enrichment instead",
            "Settings → AI: set a provider; `ollama pull qwen3:8b` first if none is downloaded",
        )
    base = (getattr(cfg, "base_url", "") or _DEFAULT_BASE.get(provider, "")).rstrip("/")
    model = str(getattr(cfg, "model", "") or "")

    payload = None
    for suffix in ("/api/tags", "/v1/models"):
        try:
            payload = probe.http(base + suffix, 2.0)
        except Exception:  # noqa: BLE001 - unreachable is a normal answer here
            payload = None
        if payload is not None:
            break
    names = _model_names(payload)
    if names is None:
        return _check(
            "llm",
            False,
            False,
            f"{provider} is not answering at {base}",
            f"start {provider}, or correct the base URL in Settings → AI",
        )
    if not names:
        return _check(
            "llm",
            False,
            False,
            f"{provider} is up at {base} with no models downloaded",
            f"ollama pull {model or 'qwen3:8b'}",
        )
    if model and model not in names:
        return _check(
            "llm",
            False,
            False,
            f"{provider} has {len(names)} models but not {model!r}",
            f"ollama pull {model}",
        )
    shown = ", ".join(names[:4]) + (f" (+{len(names) - 4} more)" if len(names) > 4 else "")
    return _check("llm", True, False, f"{provider}: {shown}", "")


def check_vault(probe: Probe) -> dict[str, Any]:
    """The vault is the only required thing — captures have nowhere to go
    without it. A vault that already holds markdown is reported as existing
    content rather than imported: the watcher already reads it."""
    if not probe.vault_dir:
        return _check(
            "vault",
            False,
            True,
            "no vault directory configured",
            "Settings → System: point the vault at any folder of .md files — "
            "an existing Obsidian vault qualifies as-is",
        )
    if probe.note_count:
        return _check(
            "vault",
            True,
            True,
            f"{probe.note_count} markdown notes already at {probe.vault_dir}, imported by the "
            "vault watcher — change it with paths.vault_dir",
            "",
        )
    ok = probe.writable(probe.vault_dir)
    return _check(
        "vault",
        ok,
        True,
        f"{probe.vault_dir} is {'writable' if ok else 'not writable'}",
        "" if ok else f"{probe.vault_dir} cannot be written to — check permissions or pick another path",
    )


_CHECKS: tuple[tuple[str, Callable[[Probe], dict[str, Any]]], ...] = (
    ("vault", check_vault),
    ("llm", _check_llm),
    ("ffmpeg", lambda p: _binary(p, "ffmpeg", "apt install ffmpeg, or pacman -S ffmpeg", ["-version"])),
    (
        "yt-dlp",
        lambda p: _binary(p, "yt-dlp", "pipx install yt-dlp (needed only for YouTube captures)", ["--version"]),
    ),
    (
        "hyprctl",
        lambda p: _binary(
            p, "hyprctl", "Hyprland only — without it the activity timeline stays empty", ["version"]
        ),
    ),
)


# Which checks are mandatory, kept beside the list rather than inside each
# function: the exception fallback below has to reproduce it, and a check that
# *crashed* must not be reported as optional just because it blew up.
_REQUIRED = frozenset({"vault"})


def order_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Required first, everything else in declaration order.

    Split out so the guarantee is testable against a mixed input. Asserting it
    on `check_all`'s own output proved nothing: the one required check is
    declared first, so the list was already sorted.
    """
    return sorted(checks, key=lambda c: not c["required"])


def check_all(probe: Probe | None = None) -> dict[str, Any]:
    """Every check, required failures first.

    A first-run screen gets read once, so the thing that will not work at all
    must not sit below three things that will.
    """
    probe = probe or Probe()
    checks: list[dict[str, Any]] = []
    for name, fn in _CHECKS:
        try:
            checks.append(fn(probe))
        except Exception as exc:  # noqa: BLE001 - one broken check costs one row
            checks.append(
                _check(name, False, name in _REQUIRED, f"check failed: {type(exc).__name__}: {exc}", "")
            )
    ordered = order_checks(checks)
    return {"ok": all(c["ok"] for c in ordered if c["required"]), "checks": ordered}