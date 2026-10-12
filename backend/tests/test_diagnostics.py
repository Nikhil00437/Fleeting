"""#395: the bundle a user attaches to a bug report.

The security property is the whole reason this is worth careful tests. A
diagnostics bundle is *meant* to be pasted into a chat window or a GitHub
issue, which is the least private place a secret can end up — and this
app's config carries an LLM API key, a bearer token for its own API, and a
HuggingFace token. A bundle that leaked any of them would be a worse bug than
the one the user was reporting.

So the rule is a **denylist over the entire config**, not a whitelist of fields
to include. A whitelist would silently omit settings the user needs to see and
would need editing every time a field is added; a denylist fails safe, because
a new secret-bearing field is redacted by default until someone notices it is
not one.

The other half of the property is that redaction is verifiable: the tests below
assert the secret values are absent from the *serialised bundle*, not merely
absent from a dict, because that is the artifact that leaves the machine.
"""

from __future__ import annotations

import json
from pathlib import Path


from fleeting.config import Config
from fleeting.diagnostics import SET, _is_secret, build_bundle, redact_config

SECRETS = {
    "llm": {"api_key": "sk-SUPERSECRET-LLM-KEY"},
    "activity": {"api_token": "tok-SUPERSECRET-ACTIVITY"},
    "transcribe": {"hf_token": "hf_SUPERSECRET_HUGGINGFACE"},
}


def _configured() -> Config:
    cfg = Config()
    cfg.llm.api_key = SECRETS["llm"]["api_key"]
    cfg.llm.base_url = "http://127.0.0.1:11434"
    cfg.llm.model = "qwen3:8b"
    cfg.activity.api_token = SECRETS["activity"]["api_token"]
    cfg.activity.enabled = True
    cfg.transcribe.hf_token = SECRETS["transcribe"]["hf_token"]
    return cfg


def _serialised(obj) -> str:
    return json.dumps(obj, default=str)


# ---- the property that matters -------------------------------------------


def test_no_secret_reaches_the_serialised_bundle() -> None:
    """Asserted on the serialised form: that is what leaves the machine."""
    text = _serialised(redact_config(_configured()))
    for name, secret in ((k, v) for d in SECRETS.values() for k, v in d.items()):
        assert secret not in text, f"{name} leaked into the bundle"
    # and the literal hints
    for secret in SECRETS.values():
        for value in secret.values():
            assert value not in text


def test_a_secret_is_reported_as_set_not_as_its_length() -> None:
    """Length is still information. "set" is all the user needs."""
    out = redact_config(_configured())
    assert out["llm"]["api_key"] == "<set>"
    assert out["activity"]["api_token"] == "<set>"


def test_an_unset_secret_is_left_empty() -> None:
    cfg = Config()
    cfg.llm.api_key = ""
    out = redact_config(cfg)
    assert out["llm"]["api_key"] == ""


def test_a_hand_added_secret_looking_key_is_also_redacted() -> None:
    """The denylist must not depend on the field being one of ours."""
    cfg = _configured()
    cfg.llm.my_own_password = "hunter2"  # type: ignore[attr-defined]
    text = _serialised(redact_config(cfg))
    assert "hunter2" not in text


def test_no_secret_survives_across_the_whole_config() -> None:
    """The property, over every field rather than three hand-picked ones."""
    out = redact_config(_configured())
    for section, values in out.items():
        for name, value in values.items():
            if _is_secret(name):
                assert value in ("", SET), f"{section}.{name} was not redacted"


def test_ordinary_settings_are_still_visible() -> None:
    """Redaction must not turn the bundle into a useless list of `<set>`."""
    out = redact_config(_configured())
    assert out["llm"]["model"] == "qwen3:8b"
    assert out["llm"]["base_url"] == "http://127.0.0.1:11434"
    assert out["activity"]["enabled"] is True


# ---- the log tail ---------------------------------------------------------


def test_json_log_lines_are_parsed(tmp_path: Path) -> None:
    log = tmp_path / "fleeting.log"
    log.write_text(
        '{"level": "ERROR", "logger": "fleeting.process", "message": "boom"}\n'
        '{"level": "INFO", "logger": "fleeting.main", "message": "ready"}\n'
    )
    entries = _tail(log, min_level="WARNING")
    assert len(entries) == 1
    assert entries[0]["message"] == "boom"


def test_text_log_lines_survive_as_raw(tmp_path: Path) -> None:
    """The default format is text, so this path is the common one."""
    log = tmp_path / "fleeting.log"
    log.write_text(
        "2026-10-12 10:00:00,000 WARNING fleeting.x: something odd\n"
        "2026-10-12 10:00:01,000 INFO fleeting.main: ready\n"
    )
    entries = _tail(log, min_level="WARNING")
    assert len(entries) == 1
    assert "something odd" in entries[0]["message"]


def test_a_missing_log_is_not_an_error(tmp_path: Path) -> None:
    assert _tail(tmp_path / "absent.log", min_level="WARNING") == []


def test_a_truncated_last_line_does_not_break_the_bundle(tmp_path: Path) -> None:
    log = tmp_path / "fleeting.log"
    log.write_text(
        '{"level": "ERROR", "message": "one"}\n{"level": "ERRO'
    )
    entries = _tail(log, min_level="ERROR")
    assert [e.get("message") for e in entries if "message" in e] == ["one"]


def test_the_tail_is_bounded(tmp_path: Path) -> None:
    """A 6 MB log must not become a 6 MB attachment.

    Two separate bounds, so both are exercised: `limit` caps how many records
    come back, and `max_bytes` caps how much of the file is read at all. The
    second is what stops a huge log being slurped into memory just to throw
    most of it away.
    """
    log = tmp_path / "fleeting.log"
    log.write_text("".join(f'{{"level":"INFO","message":"{i}"}}\n' for i in range(5000)))
    entries = _tail(log, min_level="INFO", limit=25)
    assert len(entries) == 25
    # The newest survive, not the oldest.
    assert entries[-1]["message"] == "4999"


def test_only_the_end_of_the_file_is_read(tmp_path: Path) -> None:
    """Past the default bound, the oldest records are unreachable — by design.

    Uses the **default** `max_bytes` on purpose. The first version passed the
    parameter explicitly, so raising the default left it untouched and the test
    passed with the bound removed; the default is what the endpoint uses. The
    first version at all also wrote 5,000 short lines that never reached the
    bound, so asserting only a count passed either way.
    """
    from fleeting.diagnostics import tail_log

    log = tmp_path / "fleeting.log"
    padding = "x" * 400
    lines = [f'{{"level":"INFO","message":"{i}{padding}"}}\n' for i in range(5000)]
    log.write_text("".join(lines))
    assert log.stat().st_size > 2_000_000

    entries = tail_log(log, min_level="INFO", limit=10_000)
    assert 0 < len(entries) < len(lines), "the whole file was read"
    # Still newest-last, and the newest record is present.
    assert entries[-1]["message"].startswith("4999")


# ---- the bundle -----------------------------------------------------------


def test_the_bundle_is_serialisable_and_carries_the_basics(tmp_path: Path) -> None:
    db = tmp_path / "b.db"
    db.write_bytes(b"sqlite-ish")
    bundle = build_bundle(cfg=_configured(), log_path=tmp_path / "absent.log", db_path=db)
    text = _serialised(bundle)
    for name, secret in ((k, v) for d in SECRETS.values() for k, v in d.items()):
        assert secret not in text
    assert bundle["version"]
    assert bundle["python"]
    assert bundle["platform"]["system"]
    assert bundle["config"]["llm"]["model"] == "qwen3:8b"


def test_the_bundle_survives_a_config_holding_a_non_string(tmp_path: Path) -> None:
    """`default=str` in the serialiser is what keeps this from exploding."""
    cfg = _configured()
    cfg.llm.timeout_secs = object()  # type: ignore[assignment]
    assert _serialised(build_bundle(cfg=cfg, log_path=tmp_path / "x.log", db_path=tmp_path))


def _tail(path: Path, *, min_level: str, limit: int = 200) -> list[dict]:
    from fleeting.diagnostics import tail_log

    return tail_log(path, min_level=min_level, limit=limit)

# ---- the endpoint ---------------------------------------------------------


def test_the_endpoint_returns_a_bundle_without_secrets(client) -> None:
    """End to end through the API, which is where a leak would actually happen."""
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    body = res.json()
    assert body["version"]
    assert "config" in body and "log" in body and "database" in body
    # The running app's config may or may not hold a token, but whatever it
    # holds must not have come through.
    text = _serialised(body)
    cfg = client.app.state.st.cfg
    for secret in (cfg.llm.api_key, cfg.activity.api_token, cfg.transcribe.hf_token):
        if secret:
            assert secret not in text


def test_the_limit_is_clamped(client) -> None:
    """It is a query parameter, and the bundle is meant to be pasted somewhere."""
    assert client.get("/api/diagnostics?limit=999999").status_code == 200
    assert client.get("/api/diagnostics?limit=0").status_code == 200


def test_an_unknown_level_does_not_crash(client) -> None:
    assert client.get("/api/diagnostics?min_level=NOPE").status_code == 200
