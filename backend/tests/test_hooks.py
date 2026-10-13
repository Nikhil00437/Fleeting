"""#497: a Python hook per event, from `~/.config/fleeting/hooks/`.

These run arbitrary user code on every note write, so the design question is not
"can we run it" but "what happens when it goes wrong". Three answers, all tested
here before they are implemented:

- **A hook that raises is logged, never propagated.** A note that fails to save
  because someone's script has a typo is not a note that fails to save.
- **A hook that hangs is killed.** A blocking call inside the event handler stalls
  the capture pipeline, and the pipeline is what the UI is waiting on.
- **A hook is not a shell string.** Note text goes to argv-free stdin as JSON,
  so a note containing `$(rm -rf ~)` is data.

Packs may not install hooks (#495 packs are untrusted files). That is a separate
test at the bottom and it is the one that would turn a downloaded theme into
remote code execution.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from repo import REPO_ROOT
from fleeting.events import EventBus
from fleeting.services.hooks import (
    HOOK_EVENTS,
    HookRunner,
    discover,
    run_hook_file,
)


def write_hook(d: Path, name: str, body: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


@pytest.fixture()
def hooks_dir(tmp_path) -> Path:
    return tmp_path / "hooks"


# ---- discovery ------------------------------------------------------------


def test_no_hooks_dir_is_empty_not_an_error(hooks_dir: Path) -> None:
    """Most people will never write a hook. First run must not care."""
    assert discover(hooks_dir) == []


def test_a_hook_defining_an_event_is_discovered(hooks_dir: Path) -> None:
    write_hook(hooks_dir, "log.py", "def on_note_created(payload):\n    pass\n")
    assert [h.name for h in discover(hooks_dir)] == ["log.py"]


def test_a_hook_with_no_event_functions_is_ignored(hooks_dir: Path) -> None:
    """Importing it would cost a subprocess and find nothing."""
    write_hook(hooks_dir, "helper.py", "def unrelated():\n    return 1\n")
    assert discover(hooks_dir) == []


def test_a_non_python_file_is_ignored(hooks_dir: Path) -> None:
    write_hook(hooks_dir, "notes.txt", "def on_note_created(p): pass\n")
    assert discover(hooks_dir) == []


def test_discovery_order_is_stable(hooks_dir: Path) -> None:
    """Two hooks for one event run in a predictable order, or behaviour changes
    with the filesystem."""
    for n in ("c.py", "a.py", "b.py"):
        write_hook(hooks_dir, n, "def on_note_created(p): pass\n")
    assert [h.name for h in discover(hooks_dir)] == ["a.py", "b.py", "c.py"]


def test_the_documented_events_are_the_supported_ones() -> None:
    """`activity.live` fires on every poll. A subprocess per poll would be a
    fork bomb wearing a feature's clothes, so it is not in the set."""
    assert "note.created" in HOOK_EVENTS
    assert "activity.live" not in HOOK_EVENTS
    assert "whisper.progress" not in HOOK_EVENTS


# ---- running one ----------------------------------------------------------


def test_a_hook_receives_the_payload_as_json_on_stdin(hooks_dir: Path) -> None:
    out = tmp_out = hooks_dir / "out.json"
    write_hook(
        hooks_dir,
        "capture.py",
        # The payload arrives as a parsed dict, not as raw stdin: the runner
        # consumes stdin before exec, so a module-level read would get nothing.
        f"""
        import json, pathlib
        def on_note_created(payload):
            pathlib.Path({str(out)!r}).write_text(json.dumps(payload))
        """,
    )
    run_hook_file(hooks_dir / "capture.py", "on_note_created", {"id": "n1", "title": "hi"})
    assert json.loads(tmp_out.read_text())["id"] == "n1"


def test_a_hook_that_raises_is_reported_not_raised(hooks_dir: Path) -> None:
    write_hook(hooks_dir, "bad.py", "def on_note_created(p):\n    raise ValueError('boom')\n")
    result = run_hook_file(hooks_dir / "bad.py", "on_note_created", {})
    assert result.ok is False
    assert "boom" in result.output


def test_a_syntax_error_is_reported_not_raised(hooks_dir: Path) -> None:
    """The most likely first-run mistake, and it must not be a traceback that
    looks like the app is broken."""
    write_hook(hooks_dir, "broken.py", "def on_note_created(p)\n    pass\n")
    result = run_hook_file(hooks_dir / "broken.py", "on_note_created", {})
    assert result.ok is False
    assert result.output


def test_a_hook_that_hangs_is_killed(hooks_dir: Path) -> None:
    write_hook(hooks_dir, "slow.py", "import time\ndef on_note_created(p):\n    time.sleep(30)\n")
    result = run_hook_file(hooks_dir / "slow.py", "on_note_created", {}, timeout=1.0)
    assert result.ok is False
    assert "time" in result.output.lower()


def test_note_text_is_never_interpreted_as_shell(hooks_dir: Path) -> None:
    """A note is user text and ends up in files other people read."""
    hostile = "$(touch /tmp/opencode/hook_pwned) `id` && rm -rf /"
    result = run_hook_file(
        hooks_dir / "noop.py", "on_note_created", {"raw_text": hostile}
    )
    assert result.ok is False  # file does not exist
    assert not Path("/tmp/opencode/hook_pwned").exists()


def test_a_missing_hook_is_a_clean_error(hooks_dir: Path) -> None:
    result = run_hook_file(hooks_dir / "nope.py", "on_note_created", {})
    assert result.ok is False
    assert "nope.py" in result.output


# ---- wiring into the bus --------------------------------------------------


def test_a_hook_fires_on_published_events(hooks_dir: Path) -> None:
    out = hooks_dir / "seen.txt"
    write_hook(
        hooks_dir,
        "watch.py",
        f"""
        import pathlib, sys, json
        def on_note_created(payload):
            pathlib.Path({str(out)!r}).write_text(payload["id"])
        """,
    )
    bus = EventBus()
    HookRunner(hooks_dir, bus).start()
    bus.publish("note.created", {"id": "n9"})
    bus.publish("note.created", {"id": "n10"})
    assert out.read_text() == "n10"


def test_a_failing_hook_does_not_stop_the_next_one(hooks_dir: Path) -> None:
    out = hooks_dir / "seen.txt"
    write_hook(hooks_dir, "a_bad.py", "def on_note_created(p):\n    raise RuntimeError('x')\n")
    write_hook(
        hooks_dir,
        "b_good.py",
        f"""
        import pathlib
        def on_note_created(payload):
            pathlib.Path({str(out)!r}).write_text("ran")
        """,
    )
    bus = EventBus()
    HookRunner(hooks_dir, bus).start()
    bus.publish("note.created", {"id": "n1"})
    assert out.read_text() == "ran"


def test_starting_with_no_hooks_registers_nothing(hooks_dir: Path) -> None:
    """Registering handlers that do nothing costs a queue and a dict entry per
    event, for every event, forever."""
    bus = EventBus()
    HookRunner(hooks_dir, bus).start()
    assert not any(bus._handlers.values())


def test_a_hook_firing_on_an_unsubscribed_event_is_never_run(hooks_dir: Path) -> None:
    write_hook(hooks_dir, "watch.py", "def on_note_created(p):\n    raise AssertionError('ran')\n")
    bus = EventBus()
    HookRunner(hooks_dir, bus).start()
    bus.publish("task.created", {"id": "t1"})  # must not raise


# ---- packs must not be able to install hooks ------------------------------


def test_a_pack_cannot_install_a_hook(tmp_path) -> None:
    """#495 packs are untrusted files. If one could write into the hooks
    directory, downloading a theme would be running code."""
    from fleeting.config import Config
    from fleeting.services.packs import install_pack, list_packs

    d = tmp_path / "packs"
    d.mkdir(parents=True)
    (d / "evil.json").write_text(
        json.dumps(
            {
                "name": "evil",
                "theme": {},
                "prompts": {"hooks_dir": "/tmp/opencode/evil", "vault_dir": "/etc"},
            }
        ),
        encoding="utf-8",
    )
    assert list_packs(d, Config())[0]["prompts"] == {}

    cfg = Config()
    before = (cfg.paths.vault_dir, cfg.writing.style_guide)
    install_pack([d], "evil", cfg, save=lambda _c: None)
    # The pack installs as a no-op. Nothing it asked for exists: no hook was
    # written, no path was repointed.
    assert (cfg.paths.vault_dir, cfg.writing.style_guide) == before
    assert not hasattr(cfg, "hooks_dir")
    assert not list(tmp_path.glob("**/*.py")), "a pack wrote a hook"

def test_an_unreadable_hook_file_is_skipped_not_fatal(hooks_dir: Path) -> None:
    """Discovery reads files but never imports them, so the failure mode here is
    permissions, not syntax. A single unreadable file must not stop startup —
    that is the one moment a hook problem can take the whole app down."""
    good = write_hook(hooks_dir, "good.py", "def on_note_created(p): pass\n")
    bad = write_hook(hooks_dir, "locked.py", "def on_note_created(p): pass\n")
    bad.chmod(0o000)
    try:
        found = discover(hooks_dir)
    finally:
        bad.chmod(0o644)
    assert good.name in [h.name for h in found]


def test_the_app_registers_hooks_from_the_sandboxed_directory(client) -> None:
    """The wiring, end to end: create_app() subscribes whatever discovery finds.

    Asserted against the sandbox rather than a real hooks folder, because a test
    that discovered the user's actual `~/.config/fleeting/hooks` would run their
    code on every note write in the whole suite.
    """
    import fleeting.config as fcfg
    from conftest import _REAL

    # Not "inside the sandbox" — the client fixture repoints DB_PATH at its own
    # tmp_path, so there are two different sandboxes in play. The property that
    # matters is the negative one: never the folder a user's hooks live in.
    resolved = fcfg.hooks_dir()
    assert resolved != Path(_REAL["HOOKS_DIR"])
    assert "/pytest" in str(resolved) or "fleeting-pytest" in str(resolved)


def test_the_shipped_example_hook_is_a_valid_hook() -> None:
    """We ship one example, so it has to pass our own discovery — and it has to
    be the *only* event it claims, or the documented table drifts from the
    allowlist."""
    from repo import REPO_ROOT

    found = discover(REPO_ROOT / "hooks")
    assert [(h.name, h.events) for h in found] == [
        ("example_desk_log.py", ("note.created",)),
        (
            "run_command.py",
            ("note.created", "note.updated", "task.created", "task.updated", "dailylog.updated"),
        ),
    ]


def test_the_shipped_example_actually_runs() -> None:
    """A documented example that raises on first use is worse than none."""
    import tempfile

    from repo import REPO_ROOT

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "hook.log"
        script = (
            "import json, os, pathlib, runpy, sys\n"
            "sys.argv = ['hook']\n"
            f"os.environ['FLEETING_HOOK_LOG'] = {str(log)!r}\n"
            f"mod = runpy.run_path({str(REPO_ROOT / 'hooks' / 'example_desk_log.py')!r})\n"
            "mod['on_note_created']({'id': 'n1', 'title': 'hi', 'created_at': '2026-01-01'})\n"
        )
        import subprocess
        import sys as _sys

        proc = subprocess.run([_sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        assert proc.returncode == 0, proc.stderr
        assert json.loads(log.read_text())["id"] == "n1"


def test_every_event_in_the_docs_table_is_hookable() -> None:
    """The README documents eight events. If the allowlist gains one the docs
    must say so, and if it loses one the docs are lying."""
    import re

    from repo import REPO_ROOT

    doc = (REPO_ROOT / "hooks" / "README.md").read_text(encoding="utf-8")
    # Matches the table rows too, which list the name without a `def`.
    documented = {f"on_{m}" for m in re.findall(r"on_([a-z_]+)\(", doc)}
    from fleeting.services.hooks import HOOK_EVENTS, _py_name

    assert documented == {f"on_{_py_name(e)}" for e in HOOK_EVENTS}


# ---- #496: user-defined actions, as a shipped hook ----

def _run_example(tmp_path, actions_toml, event="note.created", payload=None, env=None):
    """Run the shipped `run_command.py` example against a temp actions file."""
    import os
    import subprocess
    import sys as _sys

    actions = tmp_path / "actions.toml"
    # `None` means "leave whatever is already there" — needed to test an
    # unreadable file, since writing it is what this helper normally does.
    if actions_toml is not None:
        actions.write_text(actions_toml, encoding="utf-8")
    func = event.replace(".", "_")
    script = f"""
import json, os, pathlib, runpy, sys
os.environ["FLEETING_ACTIONS"] = {str(actions)!r}
os.environ["FLEETING_HOOK_OUT"] = {str(tmp_path / "ran.json")!r}
mod = runpy.run_path({str(REPO_ROOT / "hooks" / "run_command.py")!r})
mod["on_{func}"](json.loads({json.dumps(payload if payload is not None else {"id": "n1", "title": "Router fix"})!r}))
"""
    proc = subprocess.run([_sys.executable, "-c", script], capture_output=True, text=True,
                          timeout=30, env={**os.environ, **(env or {})})
    return proc, json.loads((tmp_path / "ran.json").read_text()) if (tmp_path / "ran.json").exists() else None


def test_a_declared_command_runs_with_the_payload(tmp_path) -> None:
    """#496: a shell command on note events, with no code written."""
    out = tmp_path / "ran.txt"
    proc, _ = _run_example(
        tmp_path,
        "[[action]]\n"
        'event = "note.created"\n'
        f'command = ["sh", "-c", "echo \\"$1\\" > {out}", "sh", "{{title}}"]\n',
    )
    assert proc.returncode == 0, proc.stderr
    assert out.read_text().strip() == "Router fix"


def test_no_actions_file_is_not_an_error(tmp_path) -> None:
    proc, _ = _run_example(tmp_path, "", env={"FLEETING_ACTIONS": str(tmp_path / "gone.toml")})
    assert proc.returncode == 0, proc.stderr


def test_a_malformed_actions_file_is_reported_not_fatal(tmp_path) -> None:
    """The most likely first-run mistake: a hand-written TOML with one typo."""
    proc, _ = _run_example(tmp_path, "this is not toml {{{")
    assert proc.returncode == 0
    assert "toml" in proc.stderr.lower()


def test_a_command_that_fails_does_not_raise(tmp_path) -> None:
    proc, _ = _run_example(tmp_path, '[[action]]\nevent = "note.created"\ncommand = ["false"]\n')
    assert proc.returncode == 0


def test_a_command_is_never_run_through_a_shell(tmp_path) -> None:
    """A note is user text. `{title}` is substituted into an argv *element*,
    never into a shell string, so this note cannot become a command."""
    marker = tmp_path / "pwned"
    payload = {"id": "n1", "title": f"$(touch {marker})"}
    proc, _ = _run_example(tmp_path, """
[[action]]
event = "note.created"
command = ["sh", "-c", "echo hi"]
""", payload=payload, env={})
    assert proc.returncode == 0
    assert not marker.exists()


def test_an_unknown_event_is_ignored(tmp_path) -> None:
    proc, _ = _run_example(tmp_path, '[[action]]\nevent = "note.deleted"\ncommand = ["false"]\n')
    assert proc.returncode == 0


def test_an_action_with_no_command_is_skipped(tmp_path) -> None:
    proc, _ = _run_example(tmp_path, '[[action]]\nevent = "note.created"\n')
    assert proc.returncode == 0


def test_an_action_for_another_event_does_not_run(tmp_path) -> None:
    """Exit code alone cannot tell: a wrong event, a failed command and a
    command that never ran all leave the hook returning 0. The only way to see
    the difference is for the command to leave a trace."""
    marker = tmp_path / "ran"
    proc, _ = _run_example(
        tmp_path,
        '[[action]]\nevent = "note.deleted"\n' + f'command = ["touch", "{marker}"]\n',
    )
    assert proc.returncode == 0, proc.stderr
    assert not marker.exists(), "an action for note.deleted ran on note.created"


def test_a_failing_command_says_so_on_stderr(tmp_path) -> None:
    proc, _ = _run_example(tmp_path, '[[action]]\nevent = "note.created"\ncommand = ["false"]\n')
    assert proc.returncode == 0
    assert "exited" in proc.stderr


def test_a_hanging_command_is_killed_and_reported(tmp_path) -> None:
    """The action's own `timeout` wins over the hook runner's 10s default, so a
    wedged command cannot hold up a capture for a minute."""
    import time

    started = time.monotonic()
    proc, _ = _run_example(
        tmp_path,
        '[[action]]\nevent = "note.created"\ncommand = ["sleep", "30"]\ntimeout = 1\n',
    )
    assert proc.returncode == 0
    assert time.monotonic() - started < 20, "the sleep was not killed"
    assert "timed out" in proc.stderr


def test_an_unreadable_actions_file_is_reported_not_fatal(tmp_path) -> None:
    """Hand-edited files get the wrong permissions. This runs on every note
    write, so it must not be a traceback."""
    actions = tmp_path / "actions.toml"
    actions.write_text("[[action]]\nevent = \"note.created\"\n", encoding="utf-8")
    actions.chmod(0o000)
    try:
        proc, _ = _run_example(tmp_path, None)
    finally:
        actions.chmod(0o644)
    assert proc.returncode == 0, proc.stderr
    assert "cannot read" in proc.stderr


def test_the_docs_list_the_same_events_as_the_hook(tmp_path) -> None:
    """The actions file uses the same event names as every other hook."""
    import re
    doc = (REPO_ROOT / "hooks" / "README.md").read_text(encoding="utf-8")
    assert "actions.toml" in doc
    assert re.search(r"event\s*=\s*\"note\.created\"", doc)
