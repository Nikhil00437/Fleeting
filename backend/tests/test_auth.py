"""Loopback is not an authentication boundary.

The Origin check covers *browser* CSRF, but the app had no authentication at
all: any local process could `PUT /api/settings`, read every note, or
`POST /api/processes/1/kill`. `Origin` is absent from non-browser clients by
design, so the existing middleware waves them straight through.

`Host` was also unvalidated, which leaves DNS rebinding open: a page can
resolve attacker.example to 127.0.0.1 and send same-origin requests that the
Origin check sees as the app's own.

Both are closed here: a bearer token on mutating routes, and a Host allow-list.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def auth_client(client, monkeypatch):
    """A client whose app requires a token."""
    st = client.app.state.st
    st.api_token = "test-token-abc123"
    return client


AUTHED = {"Authorization": "Bearer test-token-abc123"}


# ---------------------------------------------------------------------------
# token required on mutating routes
# ---------------------------------------------------------------------------


def test_no_token_blocks_settings_write(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    r = client.put("/api/settings", json={"port": 9999})
    assert r.status_code == 401, "unauthenticated write was allowed"


def test_no_token_blocks_delete(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    r = client.post("/api/capture/text", json={"text": "secret"}, headers=AUTHED)
    nid = r.json()["id"]
    assert client.delete(f"/api/notes/{nid}").status_code == 401


def test_no_token_blocks_process_kill(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    r = client.post("/api/processes/1/kill", json={})
    assert r.status_code == 401, "unauthenticated SIGKILL was allowed"


def test_wrong_token_is_rejected(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    r = client.put(
        "/api/settings",
        json={"port": 9999},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401


def test_malformed_authorization_header_is_rejected(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    for bad in ["test-token-abc123", "Basic test-token-abc123", "Bearer", "bearer x"]:
        r = client.put("/api/settings", json={"port": 9999}, headers={"Authorization": bad})
        assert r.status_code == 401, f"accepted {bad!r}"


def test_valid_token_allows_the_write(client) -> None:
    client.app.state.st.api_token = "test-token-abc123"
    r = client.put("/api/settings", json={"port": 9999}, headers=AUTHED)
    assert r.status_code == 200
    assert client.get("/api/settings").json()["port"] == 9999


def test_reads_do_not_require_a_token(client) -> None:
    """The SPA must render before it can send a token; reads stay open."""
    client.app.state.st.api_token = "test-token-abc123"
    assert client.get("/api/notes").status_code == 200
    assert client.get("/api/health").status_code == 200


def test_health_stays_reachable_without_a_token(client) -> None:
    """The UI polls health to detect the backend; never gate it."""
    client.app.state.st.api_token = "test-token-abc123"
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] in (True, False)


# ---------------------------------------------------------------------------
# no token configured -> unchanged behaviour (single-user, backwards compatible)
# ---------------------------------------------------------------------------


def test_no_token_configured_keeps_writes_working(client) -> None:
    client.app.state.st.api_token = None
    assert client.put("/api/settings", json={"port": 8123}).status_code == 200


def test_empty_token_string_is_treated_as_unset(client) -> None:
    client.app.state.st.api_token = ""
    assert client.put("/api/settings", json={"port": 8124}).status_code == 200


# ---------------------------------------------------------------------------
# Host validation (DNS rebinding)
# ---------------------------------------------------------------------------


def test_foreign_host_header_is_rejected(client) -> None:
    """A rebound name still arrives with an attacker Host header."""
    r = client.get("/api/notes", headers={"Host": "attacker.example"})
    assert r.status_code == 421, "accepted a request with a foreign Host header"


def test_localhost_and_ip_hosts_are_accepted(client) -> None:
    for host in ("127.0.0.1", "localhost", f"127.0.0.1:{client.app.state.st.cfg.server.port}"):
        r = client.get("/api/notes", headers={"Host": host})
        assert r.status_code == 200, f"rejected legitimate Host {host!r}"


def test_host_check_applies_to_writes_too(client) -> None:
    r = client.put("/api/settings", json={"port": 1}, headers={"Host": "evil.test"})
    assert r.status_code == 421


def test_non_api_paths_are_not_host_checked(client) -> None:
    """The SPA and its assets must still load."""
    r = client.get("/index.html", headers={"Host": "attacker.example"})
    assert r.status_code in (200, 404)


# ---------------------------------------------------------------------------
# token generation + secrecy
# ---------------------------------------------------------------------------


def test_token_is_generated_when_absent(tmp_path, monkeypatch) -> None:
    import secrets

    import fleeting.config as fcfg
    from fleeting.config import Config, ensure_token

    monkeypatch.setattr(fcfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")

    tok = ensure_token(Config())
    assert tok and len(tok) >= 32, "token too short to be unguessable"
    assert secrets.compare_digest(tok, ensure_token(Config())), "not stable across calls"


def test_existing_token_is_not_rotated(tmp_path, monkeypatch) -> None:
    import fleeting.config as fcfg
    from fleeting.config import Config, ensure_token

    monkeypatch.setattr(fcfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")

    first = ensure_token(Config())
    assert ensure_token(Config()) == first


def test_token_is_never_returned_by_settings(client) -> None:
    body = client.get("/api/settings").json()
    assert "api_token" not in body
    assert "server_api_token" not in body


def test_health_never_leaks_the_token(client) -> None:
    client.app.state.st.api_token = "sk-do-not-leak-me"
    assert "sk-do-not-leak-me" not in client.get("/api/health").text