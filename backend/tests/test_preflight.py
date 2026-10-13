"""#100: tell someone what is missing before they wonder why nothing works.

Every one of these has been found the hard way during development: ffmpeg
missing means voice memos fail with a conversion error, yt-dlp missing means
YouTube captures silently do nothing, a missing `hyprctl` means the timeline is
empty forever with no indication why.

The probes are injectable so the tests do not describe *this* machine. A test
that asserts ffmpeg is installed passes here and on any dev box, and fails in
CI — which is worse than no test, because it trains you to re-run.

What this is not: a version of "pick a model" or "import a vault". Both already
exist — `[llm].enrich_model` and friends in Settings → AI, and the vault watcher
traverses `vault_dir` recursively for `.md`, which is what an Obsidian vault
already is. So those two parts of #100 are configuration, and pretending they
need code would be inventing work.
"""

from __future__ import annotations

from fleeting.services.preflight import check_all, check_vault, order_checks, Probe


def _probe(**overrides) -> Probe:
    """A machine where nothing is present unless a test says otherwise."""
    base = {
        "which": lambda name: None,
        "run": lambda cmd, timeout=5.0: (1, "", ""),
        "http": lambda url, timeout=2.0: None,
        "writable": lambda path: True,
        "vault_dir": "",
        "note_count": 0,
        "config": None,
    }
    base.update(overrides)
    return Probe(**base)


# ---- individual dependencies ----------------------------------------------


def test_a_missing_binary_is_reported_with_a_fix() -> None:
    out = check_all(_probe())["checks"]
    by_name = {c["name"]: c for c in out}
    for binary in ("ffmpeg", "yt-dlp", "hyprctl"):
        assert by_name[binary]["ok"] is False
        assert by_name[binary]["fix"], f"{binary} is missing with no advice"


def test_a_present_binary_is_ok_and_not_required() -> None:
    probe = _probe(
        which=lambda name: f"/usr/bin/{name}", run=lambda cmd, timeout=5.0: (0, "v1.2.3", "")
    )
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["ffmpeg"]["ok"] is True
    assert out["ffmpeg"]["required"] is False
    assert out["ffmpeg"]["detail"], "a passing check should say what it found"


def test_a_binary_that_breaks_is_not_ok_just_because_it_exists() -> None:
    """`which` finds it; it still may not run. `ffmpeg` in a broken PATH entry
    is the version of this that wastes an afternoon."""
    probe = _probe(
        which=lambda name: "/usr/bin/" + name, run=lambda cmd, timeout=5.0: (127, "", "not found")
    )
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["ffmpeg"]["ok"] is False


def test_no_binary_at_all_still_answers_for_everything() -> None:
    """A first-run screen must not fall over on the machine with nothing."""
    out = check_all(_probe())
    assert len(out["checks"]) >= 4
    assert out["ok"] is False, "an empty machine is not a healthy one"
    assert all(c["name"] and "ok" in c for c in out["checks"])


# ---- the LLM --------------------------------------------------------------


def test_no_llm_is_reported_but_does_not_fail_the_run() -> None:
    """The app is fully functional without one: heuristics take over. Calling
    that broken would train people to ignore the whole panel."""
    probe = _probe(
        config=type("C", (), {"llm": type("L", (), {"provider": "none", "base_url": "", "model": ""})()})()
    )
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["llm"]["ok"] is False
    assert out["llm"]["required"] is False
    assert out["llm"]["fix"]


def test_a_reachable_llm_with_no_model_is_a_distinct_problem() -> None:
    """Ollama is up but has nothing pulled is not the same as Ollama is down,
    and the fix is different: `ollama pull`, not start the server."""
    probe = _probe(
        http=lambda url, timeout=2.0: {"models": []},
        config=type("C", (), {"llm": type("L", (), {"provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": ""})()})(),
    )
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["llm"]["ok"] is False
    assert "pull" in out["llm"]["fix"]


def test_a_working_llm_is_ok() -> None:
    probe = _probe(
        http=lambda url, timeout=2.0: {"models": [{"name": "qwen3:8b"}]},
        config=type("C", (), {"llm": type("L", (), {"provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen3:8b"})()})(),
    )
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["llm"]["ok"] is True
    assert "qwen3" in out["llm"]["detail"]


# ---- storage --------------------------------------------------------------


def test_an_unwritable_vault_is_reported() -> None:
    probe = _probe(writable=lambda path: False, vault_dir="/root/nope")
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["vault"]["ok"] is False
    assert out["vault"]["required"] is True


def test_a_vault_with_notes_is_reported_as_existing_content() -> None:
    probe = _probe(vault_dir="/home/u/Documents/Obsidian", note_count=1200)
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["vault"]["ok"] is True
    assert "1200" in out["vault"]["detail"]


def test_an_existing_vault_is_pointed_out_rather_than_imported() -> None:
    """#100 says "import an existing Obsidian vault".

    The watcher already traverses `vault_dir` recursively for `.md`, so
    pointing it at one *is* the import. Saying so is the whole feature, and
    writing an importer would duplicate the watcher.
    """
    out = check_vault(_probe(vault_dir="/home/u/Documents/Obsidian", note_count=1200))
    assert "vault_dir" in out["detail"]


# ---- ordering and shape ---------------------------------------------------


def test_required_failures_are_listed_first() -> None:
    """First-run screens get read once. The thing that will not work at all
    should not be below three things that will.

    Checked through `order_checks` with a mixed input, not through `check_all`:
    the only required check happens to be declared first, so the built-in order
    already satisfied this and the test passed with the sort deleted.
    """
    mixed = [
        {"name": "ffmpeg", "ok": True, "required": False, "detail": "", "fix": ""},
        {"name": "vault", "ok": False, "required": True, "detail": "", "fix": ""},
        {"name": "yt-dlp", "ok": True, "required": False, "detail": "", "fix": ""},
    ]
    assert [c["name"] for c in order_checks(mixed)] == ["vault", "ffmpeg", "yt-dlp"]


def test_ordering_is_stable_within_a_group() -> None:
    """Reordering two optionals would make the panel jitter between refreshes
    for no reason."""
    mixed = [
        {"name": "a", "ok": True, "required": False, "detail": "", "fix": ""},
        {"name": "b", "ok": True, "required": False, "detail": "", "fix": ""},
    ]
    assert [c["name"] for c in order_checks(mixed)] == ["a", "b"]


def test_every_check_is_serialisable() -> None:
    """It goes over the API; a Path or an exception in there is a 500."""
    import json

    json.dumps(check_all(_probe()))


def test_a_probe_that_raises_does_not_take_the_panel_down() -> None:
    """One broken check must not lose the other four answers.

    Raises from `writable`, not `http`: the llm check already catches its own
    probe errors, so an http-based version of this passed with check_all's guard
    deleted entirely.
    """

    def boom(path):
        raise OSError("network on fire")

    out = check_all(_probe(writable=boom, vault_dir="/home/u/Vault"))
    assert len(out["checks"]) >= 4
    assert out["ok"] is False
    assert out["checks"][0]["name"] == "vault"


def test_a_raising_probe_names_the_cause() -> None:
    """'check failed' alone is unactionable. This is the screen someone reads
    when something is wrong, so the reason has to survive to the row."""

    def boom(path):
        raise OSError("permission denied on /mnt")

    out = check_all(_probe(writable=boom, vault_dir="/mnt/vault"))
    assert "permission denied on /mnt" in out["checks"][0]["detail"]

# ---- over the API ---------------------------------------------------------


def test_the_endpoint_answers_with_the_same_shape(client) -> None:
    """`client` is the real app, so this proves the wiring: state lookup, the
    db probe, and the config all reach the service."""
    out = client.get("/api/preflight").json()
    assert set(out) == {"ok", "checks"}
    assert [c["name"] for c in out["checks"]][0] == "vault", "required failures first"
    for c in out["checks"]:
        assert {"name", "ok", "required", "detail", "fix"} <= set(c)


def test_the_endpoint_reflects_the_configured_vault(client) -> None:
    body = client.get("/api/preflight").json()
    vault = next(c for c in body["checks"] if c["name"] == "vault")
    assert vault["required"] is True
    # The fixture redirects VAULT_DIR into a temp sandbox, so it exists and is
    # writable — the check must agree rather than report a phantom failure.
    assert vault["ok"] is True


def test_a_db_failure_degrades_one_row_not_the_response(client, monkeypatch) -> None:
    """The database is one of the things being checked. If it throws, the
    endpoint still has to answer — a first-run screen that 500s tells you
    nothing at all."""
    from fleeting.db import Database

    monkeypatch.setattr(
        Database, "count_notes", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("db gone"))
    )
    out = client.get("/api/preflight")
    assert out.status_code == 200
    vault = next(c for c in out.json()["checks"] if c["name"] == "vault")
    assert vault["ok"] is False
    assert "db gone" in vault["detail"]
    assert out.json()["ok"] is False


def test_each_binary_is_probed_with_the_form_it_actually_accepts() -> None:
    """Three different shapes, and getting one wrong reports a working tool as
    broken — the single worst thing a preflight panel can do.

    ffmpeg 9.0.1 exits 8 on `--version` and 0 on `-version`; `hyprctl` wants
    the `version` subcommand and errors on the flag. Found by running this
    against the real machine, not by reasoning about it.
    """
    seen: dict[str, list[str]] = {}

    def run(cmd, timeout=5.0):
        seen[cmd[0].rsplit("/", 1)[-1]] = cmd[1:]
        return 0, "v1", ""

    check_all(_probe(which=lambda n: "/usr/bin/" + n, run=run))
    assert seen["ffmpeg"] == ["-version"]
    assert seen["yt-dlp"] == ["--version"]
    assert seen["hyprctl"] == ["version"]


def test_a_working_ffmpeg_9_is_not_reported_broken() -> None:
    def run(cmd, timeout=5.0):
        if cmd[1:] == ["-version"]:
            return 0, "ffmpeg version n9.0.1", ""
        return 8, "", ""  # what ffmpeg 9 actually does with --version

    out = {c["name"]: c for c in check_all(_probe(which=lambda n: "/usr/bin/" + n, run=run))["checks"]}
    assert out["ffmpeg"]["ok"] is True


def test_a_configured_model_that_was_never_pulled_is_flagged() -> None:
    """Ollama is up and has models, but not the one in config. The fix is
    `ollama pull <model>` — not 'start Ollama', which is the advice given when
    the server is down and is useless here."""
    cfg = type("C", (), {"llm": type(
        "L", (), {"provider": "ollama", "base_url": "http://127.0.0.1:11434", "model": "llama9:70b"}
    )()})()
    probe = _probe(http=lambda url, timeout=2.0: {"models": [{"name": "qwen3:8b"}]}, config=cfg)
    out = {c["name"]: c for c in check_all(probe)["checks"]}
    assert out["llm"]["ok"] is False
    assert "llama9:70b" in out["llm"]["fix"]
