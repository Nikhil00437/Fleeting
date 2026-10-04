"""Tests for the custom-provider API key: auth headers, persistence, and non-leakage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import fleeting.config as fcfg
from fleeting.config import Config, LLMConfig
from fleeting.services.llm import auth_headers, check_llm


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    payload: dict = {}
    seen_headers: dict | None = None
    seen_url: str | None = None

    def __init__(self, *a, **kw) -> None:
        FakeAsyncClient.seen_headers = kw.get("headers")

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str) -> FakeResponse:
        FakeAsyncClient.seen_url = url
        return FakeResponse(FakeAsyncClient.payload)

    async def post(self, url: str, json: dict | None = None) -> FakeResponse:
        FakeAsyncClient.seen_url = url
        return FakeResponse({"choices": [{"message": {"content": "ok"}}], "embedding": [0.1]})


class FakeSyncClient:
    seen_headers: dict | None = None

    def __init__(self, *a, **kw) -> None:
        FakeSyncClient.seen_headers = kw.get("headers")

    def __enter__(self) -> "FakeSyncClient":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def post(self, url: str, json: dict | None = None) -> FakeResponse:
        return FakeResponse({"embedding": [0.1, 0.2, 0.3]})


@pytest.fixture
def fake_http(monkeypatch):
    import httpx

    FakeAsyncClient.payload = {"models": [{"name": "m", "capabilities": ["completion"]}]}
    FakeAsyncClient.seen_headers = None
    FakeSyncClient.seen_headers = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(httpx, "Client", FakeSyncClient)
    return FakeAsyncClient


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    return tmp_path / "config.toml"


# ---------------------------------------------------------------------------
# auth_headers
# ---------------------------------------------------------------------------


def test_auth_headers_empty_when_no_key() -> None:
    assert auth_headers(LLMConfig(api_key="")) == {}
    assert auth_headers(LLMConfig(api_key="   ")) == {}


def test_auth_headers_bearer_when_key_set() -> None:
    assert auth_headers(LLMConfig(api_key="sk-abc")) == {"Authorization": "Bearer sk-abc"}


# ---------------------------------------------------------------------------
# headers actually reach the server
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_discovery_sends_authorization(fake_http) -> None:
    cfg = LLMConfig(provider="custom", base_url="http://x:9000", api_key="sk-secret")
    await check_llm(cfg)
    assert FakeAsyncClient.seen_headers == {"Authorization": "Bearer sk-secret"}


@pytest.mark.anyio
async def test_discovery_omits_header_without_key(fake_http) -> None:
    cfg = LLMConfig(provider="custom", base_url="http://x:9000", api_key="")
    await check_llm(cfg)
    assert not FakeAsyncClient.seen_headers


@pytest.mark.anyio
async def test_enrichment_chat_sends_authorization(fake_http) -> None:
    """enrich() is the real chat path; request_chat only forwards what it is given."""
    from unittest.mock import patch

    from fleeting.services.llm import enrich

    cfg = LLMConfig(provider="custom", base_url="http://x:9000", model="m", api_key="sk-secret")
    reply = '{"title": "t", "summary": "s", "tags": [], "action_items": []}'
    with patch("fleeting.services.llm._parse_json_loose", return_value={"title": "t"}):
        await enrich("some captured text", cfg)

    assert FakeAsyncClient.seen_headers == {"Authorization": "Bearer sk-secret"}


@pytest.mark.anyio
async def test_request_chat_forwards_headers_verbatim(fake_http) -> None:
    from fleeting.services.llm import request_chat

    await request_chat(
        "http://x:9000/v1/chat/completions",
        {"model": "m"},
        5,
        provider="custom",
        headers={"Authorization": "Bearer direct"},
    )
    assert FakeAsyncClient.seen_headers == {"Authorization": "Bearer direct"}


def test_embeddings_send_authorization(fake_http) -> None:
    from fleeting.services.embeddings import embed_text

    cfg = Config()
    cfg.llm.provider = "custom"
    cfg.llm.base_url = "http://x:9000"
    cfg.llm.api_key = "sk-secret"

    embed_text("hello", cfg)

    assert FakeSyncClient.seen_headers == {"Authorization": "Bearer sk-secret"}


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_api_key_round_trips_through_config_file(cfg_path) -> None:
    cfg = Config()
    cfg.llm.provider = "custom"
    cfg.llm.api_key = "sk-persisted"
    fcfg.save_config(cfg)

    loaded = fcfg.load_config()

    assert loaded.llm.api_key == "sk-persisted"
    assert "sk-persisted" in cfg_path.read_text()


# ---------------------------------------------------------------------------
# the API must not hand the secret back out
# ---------------------------------------------------------------------------


def test_settings_payload_never_returns_the_key(client: TestClient) -> None:
    client.put("/api/settings", json={"llm_provider": "custom", "llm_api_key": "sk-topsecret"})

    body = client.get("/api/settings").text

    assert "sk-topsecret" not in body
    assert client.get("/api/settings").json()["llm_api_key_set"] is True


def test_settings_reports_no_key_when_unset(client: TestClient) -> None:
    assert client.get("/api/settings").json()["llm_api_key_set"] is False


def test_put_sets_the_key(client: TestClient) -> None:
    r = client.put("/api/settings", json={"llm_api_key": "sk-abc"})
    assert r.status_code == 200, r.text
    assert r.json()["llm_api_key_set"] is True
    assert client.app.state.st.cfg.llm.api_key == "sk-abc"


def test_omitting_the_key_keeps_the_existing_one(client: TestClient) -> None:
    client.put("/api/settings", json={"llm_api_key": "sk-keepme"})
    client.put("/api/settings", json={"llm_model": "something-else"})
    assert client.app.state.st.cfg.llm.api_key == "sk-keepme"


def test_empty_string_clears_the_key(client: TestClient) -> None:
    client.put("/api/settings", json={"llm_api_key": "sk-gone"})
    client.put("/api/settings", json={"llm_api_key": ""})
    assert client.app.state.st.cfg.llm.api_key == ""
    assert client.get("/api/settings").json()["llm_api_key_set"] is False


def test_probe_can_use_an_unsaved_key(client: TestClient, monkeypatch) -> None:
    """The key must be probeable before it is written to disk."""
    from fleeting.routers import settings as settings_router

    seen: dict = {}

    async def spy(cfg):
        seen["api_key"] = cfg.api_key
        return {"ok": True, "models": []}

    monkeypatch.setattr(settings_router.llm, "check_llm", spy)
    r = client.post("/api/settings/test-llm", json={"api_key": "sk-unsaved"})

    assert r.status_code == 200, r.text
    assert seen["api_key"] == "sk-unsaved"
    assert client.app.state.st.cfg.llm.api_key == ""