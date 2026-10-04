"""Tests for LLM endpoint discovery: chat-model filtering and probe overrides."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fleeting.config import LLMConfig
from fleeting.services.llm import chat_model_names, check_llm

OLLAMA_TAGS = {
    "models": [
        {"name": "llama3.2:3b", "capabilities": ["completion"]},
        {"name": "qwen2.5:7b", "capabilities": ["completion", "tools"]},
        {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
        {"name": "mxbai-embed-large", "capabilities": ["embedding"]},
    ]
}


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    """Stands in for httpx.AsyncClient, returning a canned payload."""

    payload: dict = {}
    last_url: str | None = None
    raise_exc: Exception | None = None

    def __init__(self, *a, **kw) -> None:
        pass

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def get(self, url: str) -> FakeResponse:
        FakeAsyncClient.last_url = url
        if FakeAsyncClient.raise_exc is not None:
            raise FakeAsyncClient.raise_exc
        return FakeResponse(FakeAsyncClient.payload)


@pytest.fixture
def fake_http(monkeypatch):
    import httpx

    FakeAsyncClient.payload = {}
    FakeAsyncClient.last_url = None
    FakeAsyncClient.raise_exc = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


# ---------------------------------------------------------------------------
# chat_model_names
# ---------------------------------------------------------------------------


def test_ollama_embedding_models_are_excluded() -> None:
    names = chat_model_names(OLLAMA_TAGS["models"], "ollama")
    assert names == ["llama3.2:3b", "qwen2.5:7b"]


def test_ollama_models_without_capabilities_are_kept() -> None:
    """Older Ollama builds omit capabilities; don't hide everything."""
    names = chat_model_names([{"name": "legacy-model"}], "ollama")
    assert names == ["legacy-model"]


def test_openai_compatible_reads_id_field() -> None:
    names = chat_model_names([{"id": "gpt-4o-mini"}, {"id": "local-model"}], "custom")
    assert names == ["gpt-4o-mini", "local-model"]


def test_none_is_excluded_from_openai_payload_too() -> None:
    names = chat_model_names([{"id": "a"}, {"id": None}, {"no_id": 1}], "lmstudio")
    assert names == ["a"]


# ---------------------------------------------------------------------------
# check_llm
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_check_llm_lists_only_chat_models(fake_http) -> None:
    fake_http.payload = OLLAMA_TAGS
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="")

    res = await check_llm(cfg)

    assert res["ok"] is True
    assert "llama3.2:3b" in res["models"]
    assert "nomic-embed-text:latest" not in res["models"]
    assert res["hidden"] == 2


@pytest.mark.anyio
async def test_check_llm_reports_unreachable(fake_http) -> None:
    fake_http.raise_exc = ConnectionError("refused")
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434")

    res = await check_llm(cfg)

    assert res["ok"] is False
    assert "refused" in res["detail"]
    assert res["models"] == []


@pytest.mark.anyio
async def test_check_llm_flags_configured_model_missing_from_chat_list(fake_http) -> None:
    fake_http.payload = OLLAMA_TAGS
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="nomic-embed-text")

    res = await check_llm(cfg)

    assert res["ok"] is False
    assert "nomic-embed-text" in res["detail"]
    assert "llama3.2:3b" in res["models"]


# ---------------------------------------------------------------------------
# probe overrides via the settings endpoint
# ---------------------------------------------------------------------------


def test_probe_accepts_unsaved_overrides(client: TestClient) -> None:
    """Probe a URL the user just typed, without saving it first."""
    import httpx

    seen: dict = {}

    async def spy(cfg):
        seen["provider"] = cfg.provider
        seen["base_url"] = cfg.base_url
        return {"ok": True, "models": ["x"]}

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", FakeAsyncClient)
    from fleeting.routers import settings as settings_router
    from fleeting.services import llm as llm_mod

    monkey.setattr(settings_router.llm, "check_llm", spy)
    try:
        r = client.post(
            "/api/settings/test-llm",
            json={"provider": "custom", "base_url": "http://10.0.0.5:9000"},
        )
    finally:
        monkey.undo()

    assert r.status_code == 200, r.text
    assert seen["provider"] == "custom"
    assert seen["base_url"] == "http://10.0.0.5:9000"
    # probing must not persist the override
    assert client.get("/api/settings").json()["llm_base_url"] != "http://10.0.0.5:9000"


def test_probe_without_body_uses_saved_config(client: TestClient) -> None:
    import httpx

    seen: dict = {}

    async def spy(cfg):
        seen["base_url"] = cfg.base_url
        return {"ok": True, "models": []}

    from fleeting.routers import settings as settings_router

    monkey = pytest.MonkeyPatch()
    monkey.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkey.setattr(settings_router.llm, "check_llm", spy)
    try:
        client.post("/api/settings/test-llm")
    finally:
        monkey.undo()

    saved = client.get("/api/settings").json()["llm_base_url"]
    assert seen["base_url"] == saved


def test_probe_rejects_unknown_provider(client: TestClient) -> None:
    r = client.post("/api/settings/test-llm", json={"provider": "skynet"})
    assert r.status_code == 422, r.text

# ---------------------------------------------------------------------------
# startup auto-detection
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_save_config(monkeypatch):
    """_autodetect_llm_model persists its choice; keep it out of the real config."""
    import fleeting.config as fcfg

    saved: list = []
    monkeypatch.setattr(fcfg, "save_config", lambda cfg: saved.append(cfg))
    return saved


@pytest.mark.anyio
async def test_autodetect_skips_embedding_models(fake_http, stub_save_config) -> None:
    from fleeting.config import Config
    from fleeting.main import _autodetect_llm_model

    fake_http.payload = {
        "models": [
            {"name": "nomic-embed-text:latest", "capabilities": ["embedding"]},
            {"name": "llama3.2:3b", "capabilities": ["completion"]},
        ]
    }
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:11434"
    cfg.llm.model = ""

    await _autodetect_llm_model(cfg)

    assert cfg.llm.model == "llama3.2:3b"


@pytest.mark.anyio
async def test_autodetect_leaves_model_empty_when_only_embeddings_exist(
    fake_http, stub_save_config
) -> None:
    """Better to use heuristics than to point enrichment at an embedding model."""
    from fleeting.config import Config
    from fleeting.main import _autodetect_llm_model

    fake_http.payload = {"models": [{"name": "nomic-embed-text", "capabilities": ["embedding"]}]}
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:11434"
    cfg.llm.model = ""

    await _autodetect_llm_model(cfg)

    assert cfg.llm.model == ""
    assert stub_save_config == []


@pytest.mark.anyio
async def test_autodetect_respects_an_already_chosen_model(fake_http, stub_save_config) -> None:
    from fleeting.config import Config
    from fleeting.main import _autodetect_llm_model

    fake_http.payload = {"models": [{"name": "other", "capabilities": ["completion"]}]}
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "mine"

    await _autodetect_llm_model(cfg)

    assert cfg.llm.model == "mine"
    assert FakeAsyncClient.last_url is None, "probed even though a model was already set"
