"""#497: user hooks in `~/.config/fleeting/hooks/`.

A hook is a `.py` file defining `on_<event>(payload)` functions. It is run as a
**subprocess** with the payload as JSON on stdin, and its return value ignored.
That is three decisions, each bought with something:

- **Subprocess, not import.** A hook that hangs, leaks memory, crashes the
  interpreter or calls `sys.exit` cannot take the app with it, and no hook can
  monkeypatch app internals. The cost is a fork per event, which is invisible at
  note-write frequency and would not be at `activity.live` frequency — which is
  why that event is not hookable.
- **stdin JSON, never argv or a shell.** Note text is user text and lands in
  files other people read. `$(rm -rf ~)` in a note is data.
- **The return value is ignored.** A hook that wants to change the app edits the
  database. Anything else is a second, undocumented write path into the same
  tables, and it would have to be audited separately from every other writer.

Failure is always logged, never raised. A note that fails to save because a
script has a typo is not a note that fails to save.

These files are the user's own code in their own config directory — the same
trust level as a shell alias. That stops being true if an untrusted source can
put one there, so packs cannot (asserted in `tests/test_hooks.py`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..events import EventBus

# The events a hook may implement. Deliberately the durable ones: `activity.live`
# fires on every poll and `whisper.progress` on every chunk, so a subprocess per
# event would be a fork bomb wearing a feature's clothes.
HOOK_EVENTS = (
    "note.created",
    "note.updated",
    "note.deleted",
    "task.created",
    "task.updated",
    "task.deleted",
    "dailylog.updated",
    "collections.changed",
)

DEFAULT_TIMEOUT = 10.0

# Runs the hook file's function in a child interpreter. Kept as a template so
# the payload can only reach the function through stdin — never through argv,
# where a note's contents would be visible in the process list.
_RUNNER = """
import importlib.util, json, pathlib, sys

path, func = sys.argv[1], sys.argv[2]
payload = json.loads(sys.stdin.read() or "{}")
spec = importlib.util.spec_from_file_location("fleeting_hook", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
fn = getattr(module, func, None)
if fn is None:
    sys.stderr.write("hook has no %s\\n" % func)
    raise SystemExit(0)
result = fn(payload)
if result is not None:
    sys.stdout.write(json.dumps(result, default=str))
"""


@dataclass(frozen=True)
class Hook:
    path: Path
    name: str
    events: tuple[str, ...]


@dataclass(frozen=True)
class HookResult:
    ok: bool
    output: str
    returncode: int


def discover(directory: Path) -> list[Hook]:
    """Every `.py` in `directory` that defines at least one supported event.

    Files are read, not imported: importing at discovery time would execute
    someone's code before any event has happened, and a syntax error in one hook
    would then be indistinguishable from a broken app.
    """
    try:
        files = sorted(Path(directory).glob("*.py"))
    except OSError:
        return []
    hooks: list[Hook] = []
    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        events = tuple(e for e in HOOK_EVENTS if f"def on_{_py_name(e)}" in source)
        if events:
            hooks.append(Hook(path=path, name=path.name, events=events))
    return hooks


def _py_name(event: str) -> str:
    """`note.created` -> `note_created`."""
    return event.replace(".", "_")


def run_hook_file(
    path: Path, func: str, payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT
) -> HookResult:
    """Run one function. Always returns; never raises.

    The caller is a note being written, so the only acceptable failure mode is
    a log line.
    """
    path = Path(path)
    if not path.exists():
        return HookResult(False, f"{path.name}: file not found", 1)
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-c", _RUNNER, str(path), func],
            input=json.dumps(payload, default=str),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return HookResult(False, f"{path.name}: timed out after {timeout:g}s — killed", 1)
    except OSError as exc:
        return HookResult(False, f"{path.name}: could not start ({exc})", 1)
    if proc.returncode != 0:
        return HookResult(False, f"{path.name}: {proc.stderr.strip()[:500]}", proc.returncode)
    return HookResult(True, proc.stdout.strip()[:2000], 0)


class HookRunner:
    """Subscribes discovered hooks to the bus. One handler per hookable event."""

    def __init__(self, directory: Path, bus: EventBus, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.directory = Path(directory)
        self.bus = bus
        self.timeout = timeout
        self.hooks: list[Hook] = []

    def start(self) -> list[Hook]:
        self.hooks = discover(self.directory)
        # No early return for "no hooks": with an empty list every event below
        # finds no handlers and continues, so the guard bought nothing and could
        # not be distinguished from the fall-through by any test.
        for event in HOOK_EVENTS:
            func = f"on_{_py_name(event)}"
            handlers = [h for h in self.hooks if event in h.events]
            if not handlers:
                continue
            # One closure per event, not per hook: the bus calls handlers in
            # order, and a hook that raises must not stop the ones after it.
            def make(event_name: str = event, func_name: str = func) -> Any:
                def handler(payload: Any) -> None:
                    self._fire(event_name, payload, func_name)

                return handler

            self.bus.subscribe(event, make())
        return self.hooks

    def _fire(self, event: str, payload: Any, func: str) -> None:
        data = payload if isinstance(payload, dict) else {"value": payload}
        for hook in self.hooks:
            if event not in hook.events:
                continue
            result = run_hook_file(hook.path, func, data, self.timeout)
            if not result.ok:
                # Logged at warning, not exception: a broken hook is the user's
                # script to fix, and a traceback per note write buries the real
                # problem somewhere in the log nobody reads.
                import logging

                logging.getLogger("fleeting.hooks").warning("hook %s: %s", event, result.output)