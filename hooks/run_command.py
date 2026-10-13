"""#496: run a command when something happens — with no code written.

Copy this file to `~/.config/fleeting/hooks/` and point it at a config:

    # ~/.config/fleeting/actions.toml
    [[action]]
    event = "note.created"
    command = ["notify-send", "Fleeting", "{title}"]

Every event name is the same as any other hook (`note.created`,
`task.completed`, ...). `command` is an **argv list**, never a shell string, so a
note containing `$(rm -rf ~)` is an argument and not a command. `{title}` and
`{id}` are substituted *into argv elements* — they can change what a command
sees, never what gets run.

This is a shipped hook rather than a second dispatch engine on purpose. The
timeout, the isolation and the failure handling already exist in #497, and a
parallel config-driven dispatcher would need its own copy of all three — the
same hardening, maintained twice, drifting apart.

This file is self-contained: copy it, read it, change it. It has no imports from
the app.
"""

import json
import os
import pathlib
import shlex
import subprocess
import sys
import tomllib

ACTIONS = pathlib.Path(
    os.environ.get("FLEETING_ACTIONS", "~/.config/fleeting/actions.toml")
).expanduser()

TIMEOUT = float(os.environ.get("FLEETING_ACTION_TIMEOUT", "10"))

# Substituted into argv elements, never into a shell string.
FIELDS = ("id", "title", "type", "created_at")


def _expand(value, payload):
    """`{title}` -> the note's title. Unknown placeholders are left alone."""
    if not isinstance(value, str):
        return value
    out = value
    for key in FIELDS:
        token = "{" + key + "}"
        if token in out:
            out = out.replace(token, str(payload.get(key) or ""))
    return out


def _load():
    """The actions file, or nothing. A broken file is a message, not a crash —
    this runs on every note write, and a traceback per capture buries whatever
    the user is actually trying to debug."""
    try:
        raw = ACTIONS.read_bytes()
    except FileNotFoundError:
        return []
    except OSError as exc:
        print("run_command: cannot read %s: %s" % (ACTIONS, exc), file=sys.stderr)
        return []
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        print("run_command: %s is not valid toml: %s" % (ACTIONS.name, exc), file=sys.stderr)
        return []
    actions = data.get("action", [])
    return actions if isinstance(actions, list) else []


def _run(payload, event):
    for action in _load():
        if not isinstance(action, dict) or action.get("event") != event:
            continue
        command = action.get("command")
        if not isinstance(command, list) or not command:
            print(
                "run_command: an action for %s has no `command` list — skipping" % event,
                file=sys.stderr,
            )
            continue
        argv = [str(_expand(part, payload)) for part in command]
        try:
            proc = subprocess.run(
                argv,
                timeout=float(action.get("timeout", TIMEOUT)),
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            print("run_command: %s timed out — killed" % argv[0], file=sys.stderr)
            continue
        except (OSError, ValueError) as exc:
            print("run_command: cannot run %s: %s" % (argv[0], exc), file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(
                "run_command: %s exited %d: %s"
                % (argv[0], proc.returncode, (proc.stderr or "").strip()[:300]),
                file=sys.stderr,
            )


# One function per event, so discovery sees them. Each is a line because a hook
# file that imports this one instead of copying it would stop being copyable.


def on_note_created(payload):
    _run(payload, "note.created")


def on_note_updated(payload):
    _run(payload, "note.updated")


def on_task_created(payload):
    _run(payload, "task.created")


def on_task_updated(payload):
    _run(payload, "task.updated")


def on_dailylog_updated(payload):
    _run(payload, "dailylog.updated")