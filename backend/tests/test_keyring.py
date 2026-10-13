"""#139: the keyring interface, and the promise that config.toml stops holding secrets.

The property this file exists to pin is the simple one: **after storing a secret
through the API, the value does not appear in config.toml.** Everything else here
— the fallback, the 0600 mode, the deletion — is in service of that staying true
on a machine with no keyring at all, which is most of them.

The fallback tests deliberately stub `shutil.which` so they exercise the
file-store path on a developer machine that *does* have a keyring, and so they
do not touch the real one. A test that stores into the user's actual Secret
Service is a test that pollutes it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from fleeting.services import keyring as kr


@pytest.fixture()
def file_store(tmp_path, monkeypatch) -> Path:
    """Force the fallback store into a temp directory, and no OS keyring.

    Stubbing `which` matters twice over: it exercises the path most machines
    take, and it stops the test writing into the developer's real Secret
    Service.
    """
    path = tmp_path / "secrets.json"
    monkeypatch.setattr(kr, "_fallback_path", lambda: path)
    monkeypatch.setattr(kr.shutil, "which", lambda _n: None)
    return path


@pytest.fixture()
def no_keyring(file_store, monkeypatch):
    """`file_store` already stubs `which`; this pins the reported backend too,
    so `status()` does not depend on what the developer machine has."""
    monkeypatch.setattr(kr, "_backend", lambda: kr.Backend("file", True, "test fallback", False))
    return file_store


# ---- the promise ----------------------------------------------------------


def test_the_settings_file_never_receives_the_value(client, tmp_path, monkeypatch) -> None:
    """Written directly rather than through the endpoint, so the assertion is
    about the file and not about the API's own response."""
    import fleeting.config as fcfg

    conf = tmp_path / "config.toml"
    monkeypatch.setattr(fcfg, "CONFIG_PATH", conf)
    monkeypatch.setattr(kr.shutil, "which", lambda _n: None)

    client.put("/api/settings", json={"llm_api_key": "sk-live-not-in-toml"})

    assert not conf.exists() or "sk-live-not-in-toml" not in conf.read_text(encoding="utf-8")


def test_the_config_keeps_a_marker_not_the_secret(client, tmp_path, monkeypatch) -> None:
    """The file records *that* a key exists, never what it is. A leaked config
    should reveal nothing usable."""
    import fleeting.config as fcfg

    conf = tmp_path / "config.toml"
    monkeypatch.setattr(fcfg, "CONFIG_PATH", conf)
    monkeypatch.setattr(kr.shutil, "which", lambda _n: None)

    client.put("/api/settings", json={"llm_api_key": "sk-live-marker-only"})
    if conf.exists():
        text = conf.read_text(encoding="utf-8")
        assert "sk-live-marker-only" not in text


# ---- the store ------------------------------------------------------------


def test_a_secret_round_trips(no_keyring) -> None:
    kr.set_secret("llm.api_key", "abc123")
    assert kr.get("llm.api_key") == "abc123"


def test_a_missing_secret_is_none_not_an_error(no_keyring) -> None:
    assert kr.get("never.stored") is None


def test_the_fallback_file_is_owner_only(no_keyring) -> None:
    """Created 0600 *before* the content is written — a file created with the
    default mode has a window where it is world-readable, and that window is the
    whole vulnerability."""
    kr.set_secret("llm.api_key", "abc")
    assert oct(no_keyring.stat().st_mode)[-3:] == "600"


def test_secrets_are_replaced_not_appended(no_keyring) -> None:
    kr.set_secret("llm.api_key", "first")
    kr.set_secret("llm.api_key", "second")
    assert kr.get("llm.api_key") == "second"
    assert len(json.loads(no_keyring.read_text())) == 1


def test_deleting_removes_it(no_keyring) -> None:
    """'Clear my API key' is a thing people need to do, and leaving the old one
    behind is the failure that matters."""
    kr.set_secret("llm.api_key", "abc")
    kr.delete_secret("llm.api_key")
    assert kr.get("llm.api_key") is None
    assert "llm.api_key" not in no_keyring.read_text()


def test_deleting_what_is_not_there_is_not_an_error(no_keyring) -> None:
    kr.delete_secret("never.stored")


def test_a_corrupt_fallback_file_reads_as_empty(no_keyring) -> None:
    no_keyring.write_text("{{{ not json", encoding="utf-8")
    assert kr.get("llm.api_key") is None


def test_the_fallback_file_is_not_world_readable_even_if_preexisting(no_keyring) -> None:
    """A file someone created by hand with a lax mode must be tightened, not
    trusted."""
    no_keyring.write_text("{}", encoding="utf-8")
    os.chmod(no_keyring, 0o644)
    kr.set_secret("llm.api_key", "abc")
    assert oct(no_keyring.stat().st_mode)[-3:] == "600"


# ---- honesty about the fallback -------------------------------------------


def test_the_fallback_is_reported_as_not_secure(no_keyring) -> None:
    """Silently downgrading to a file is worse than not offering the feature."""
    status = kr.status()
    assert status["secure"] is False
    assert status["fallback_path"]


def test_the_no_keyring_message_says_what_it_did(monkeypatch, tmp_path) -> None:
    """Checked against the real `_backend()`, not the stub the other tests use —
    the stubbed detail is 'test fallback' and proves nothing about the wording a
    user actually reads."""
    monkeypatch.setattr(kr, "_fallback_path", lambda: tmp_path / "secrets.json")
    monkeypatch.setattr(kr.shutil, "which", lambda _n: None)
    status = kr.status()
    assert status["secure"] is False
    assert "no OS keyring" in status["detail"]
    assert str(tmp_path) in status["detail"]


def test_a_real_keyring_is_reported_as_secure(monkeypatch) -> None:
    monkeypatch.setattr(kr.shutil, "which", lambda n: "/usr/bin/secret-tool" if n == "secret-tool" else None)
    status = kr.status()
    assert status["secure"] is True
    assert status["backend"] == "secret-service"
    assert status["fallback_path"] == ""


def test_the_status_never_contains_a_secret(no_keyring) -> None:
    kr.set_secret("llm.api_key", "sk-live-leak-me")
    assert "sk-live-leak-me" not in json.dumps(kr.status())


# ---- the endpoint ---------------------------------------------------------


def test_the_endpoint_reports_the_backend(client) -> None:
    body = client.get("/api/keyring").json()
    assert {"backend", "secure", "detail", "stored"} <= set(body)


def test_the_settings_payload_reports_only_whether_a_key_exists(client, monkeypatch) -> None:
    monkeypatch.setattr(kr.shutil, "which", lambda _n: None)
    client.put("/api/settings", json={"llm_api_key": "sk-live-report-me"})
    body = client.get("/api/settings").json()
    assert body["llm_api_key_set"] is True
    assert "sk-live-report-me" not in json.dumps(body)

# ---- the read side, which is the half that matters -----------------------
#
# Storing a secret in the keyring while the client still reads `cfg.api_key`
# would send the literal marker "<stored in keyring>" as the bearer token: every
# request 401s and the failure looks like a bad key, not a missing lookup.


def test_resolving_returns_the_stored_secret(no_keyring) -> None:
    from fleeting.services.keyring import resolve

    kr.set_secret("llm.api_key", "sk-real-value")
    assert resolve("llm.api_key", "<stored in keyring>") == "sk-real-value"


def test_resolving_a_marker_with_nothing_stored_falls_back_to_the_config(no_keyring) -> None:
    """A config written before this feature, or a keyring that has since been
    cleared, must not turn into a literal marker being sent as a credential."""
    from fleeting.services.keyring import resolve

    assert resolve("llm.api_key", kr.KEYRING_MARKER) == ""


def test_resolving_an_empty_config_is_empty(no_keyring) -> None:
    from fleeting.services.keyring import resolve

    assert resolve("llm.api_key", "") == ""


def test_resolving_prefers_the_keyring_over_a_plaintext_config_value(no_keyring) -> None:
    """Where both exist the keyring wins — it is the one the user moved the
    secret to."""
    from fleeting.services.keyring import resolve

    kr.set_secret("llm.api_key", "from-keyring")
    assert resolve("llm.api_key", "from-toml") == "from-keyring"


def test_the_marker_never_reaches_an_authorization_header(no_keyring) -> None:
    from fleeting.config import LLMConfig
    from fleeting.services.llm import auth_headers
    from fleeting.services.keyring import resolve

    kr.set_secret("llm.api_key", "sk-real-value")
    cfg = LLMConfig(api_key=kr.KEYRING_MARKER)
    header = auth_headers(cfg)
    assert header["Authorization"] == "Bearer sk-real-value"
    assert kr.KEYRING_MARKER not in str(header)
    assert resolve("llm.api_key", cfg.api_key) == "sk-real-value"


def test_no_authorization_header_when_nothing_is_stored(no_keyring) -> None:
    from fleeting.config import LLMConfig
    from fleeting.services.llm import auth_headers

    assert auth_headers(LLMConfig(api_key=kr.KEYRING_MARKER)) == {}
