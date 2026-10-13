"""#195: config flags for the experimental endpoints.

Config.toml already has per-section toggles — `[llm] provider`, `[activity]
enabled`, `[paths] vault_sync`. So a flag *framework* would be a second way to
do a thing that works. What is missing is a single consistent gate for endpoints
that shipped without a UI behind them, so they can be tried and then turned off.

Three of those exist: `GET /notes/tone`, `POST /benchmark/run`, and #101's pinned
context. All three are reachable and undocumented, which is the worst of both —
you cannot see them and you cannot switch them off.

They default **off**. An endpoint nobody wired up should not be silently live in
someone's install; opting in is one line of config.
"""

from __future__ import annotations

import pytest

from fleeting.config import ExperimentalConfig, load_config


@pytest.fixture()
def cfg(tmp_path, monkeypatch) -> ExperimentalConfig:
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    return load_config().experimental


# ---- the shape ------------------------------------------------------------


def test_everything_is_off_by_default(cfg: ExperimentalConfig) -> None:
    """An endpoint with no UI behind it should not be live in someone's install."""
    assert cfg.tone is False
    assert cfg.benchmark is False
    assert cfg.pinned_context is False


def test_they_can_be_turned_on_individually(tmp_path, monkeypatch) -> None:
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text("[experimental]\ntone = true\n")
    exp = load_config().experimental
    assert exp.tone is True
    assert exp.benchmark is False, "enabling one must not enable another"
    assert exp.pinned_context is False


def test_the_section_survives_a_save(tmp_path, monkeypatch) -> None:
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    c = load_config()
    c.experimental.tone = True
    fcfg.save_config(c)
    assert load_config().experimental.tone is True


# ---- the gate -------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/notes/tone"),
        ("post", "/api/benchmark/run"),
        ("get", "/api/assistant/chats/abc/context"),
    ],
)
def test_a_gated_endpoint_is_absent_by_default(client, method: str, path: str) -> None:
    """404, not 403.

    A 403 confirms the route exists, which is the thing you are trying to avoid
    telling someone about it. 404 is what an endpoint that is not there looks
    like — and the API contract check does not then flag the frontend for
    calling a route the server does not have.
    """
    res = client.post(path, json={}) if method == "post" else client.get(path)
    assert res.status_code == 404, res.text


def test_turning_one_on_makes_only_that_one_reachable(client) -> None:
    st = client.app.state.st
    st.cfg.experimental.tone = True
    try:
        assert client.get("/api/notes/tone").status_code == 200
        assert client.post("/api/benchmark/run", json={}).status_code == 404
    finally:
        st.cfg.experimental.tone = False


def test_the_gate_does_not_swallow_a_bad_request(client) -> None:
    """Enabled, the endpoint still validates. The flag is not an escape hatch."""
    st = client.app.state.st
    st.cfg.experimental.benchmark = True
    try:
        # No models given — that is a 422 from the route, not a 404 from the gate.
        assert client.post("/api/benchmark/run", json={"models": [""]}).status_code == 422
    finally:
        st.cfg.experimental.benchmark = False


# ---- what the gate must not break -----------------------------------------


def test_ordinary_endpoints_are_unaffected(client) -> None:
    for path in ("/api/health", "/api/notes", "/api/settings"):
        assert client.get(path).status_code == 200, path


def test_a_disabled_endpoint_still_gets_the_host_guard(client) -> None:
    """The flag must not become the thing keeping someone out.

    A foreign `Host` is rejected with 421 before any route runs, so a disabled
    endpoint answers 421 rather than 404 — which is the proof that it is gated
    by the ordinary middleware and not standing in front of it.
    """
    res = client.get("/api/notes/tone", headers={"Host": "evil.example"})
    assert res.status_code == 421, res.text

def test_health_reports_which_flags_are_on(client) -> None:
    """A flag you cannot read is a flag you cannot remember you set."""
    body = client.get("/api/health").json()
    assert body["experimental"] == {
        "tone": False,
        "benchmark": False,
        "pinned_context": False,
    }

    st = client.app.state.st
    st.cfg.experimental.tone = True
    try:
        assert client.get("/api/health").json()["experimental"]["tone"] is True
    finally:
        st.cfg.experimental.tone = False
