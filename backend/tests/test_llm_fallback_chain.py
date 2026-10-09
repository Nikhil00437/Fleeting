"""#266 LLM fallback chains.

A local model can be mid-pull, out of memory, or simply gone. Today the first
failure drops straight to heuristics, which quietly turns "my 7b model was
loading" into "this note has no title". A chain buys a second, smaller model a
chance before giving up on the model entirely — and each step gets its own
timeout, so a hanging model cannot eat the whole budget.
"""

from __future__ import annotations

import httpx
import pytest

from fleeting.config import LLMConfig
from fleeting.services.llm import LLMUnavailable, enrich_chain, model_chain


def _cfg(*models: str, timeout: int = 120) -> LLMConfig:
    return LLMConfig(provider="ollama", base_url="http://x:11434", model=models[0] if models else "", fallback_models=",".join(models[1:]), timeout_secs=timeout)


def test_model_chain_dedupes_and_preserves_order() -> None:
    assert model_chain(_cfg("a", "b", "a")) == ["a", "b"]


def test_model_chain_with_no_fallbacks_is_just_the_model() -> None:
    assert model_chain(_cfg("only")) == ["only"]


def test_model_chain_ignores_blanks() -> None:
    cfg = LLMConfig(provider="ollama", model="a", fallback_models=" b ,, c ")
    assert model_chain(cfg) == ["a", "b", "c"]


def test_model_chain_is_empty_when_no_model_is_configured() -> None:
    cfg = LLMConfig(provider="ollama", model="", fallback_models="")
    assert model_chain(cfg) == []


@pytest.mark.anyio
async def test_chain_falls_through_to_the_second_model(monkeypatch) -> None:
    cfg = _cfg("big", "small", timeout=10)
    tried: list[str] = []

    async def fake_post(url, payload, timeout, headers=None):
        tried.append(payload["model"])
        if payload["model"] == "big":
            raise httpx.ConnectError("connection refused")
        return '{"title": "from small", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr("fleeting.services.llm._post_chat", fake_post)

    out = await enrich_chain("some captured text", cfg)
    assert out["title"] == "from small"
    assert tried == ["big", "small"]


@pytest.mark.anyio
async def test_each_step_gets_its_own_timeout(monkeypatch) -> None:
    """A 3-model chain must not take 3x the configured timeout."""
    cfg = _cfg("a", "b", "c", timeout=30)
    timeouts: list[float] = []

    async def fake_post(url, payload, timeout, headers=None):
        timeouts.append(timeout)
        if payload["model"] != "c":
            raise httpx.ConnectError("nope")
        return '{"title": "t", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr("fleeting.services.llm._post_chat", fake_post)

    await enrich_chain("text", cfg)
    assert len(timeouts) == 3
    assert all(t == pytest.approx(10.0) for t in timeouts), timeouts


@pytest.mark.anyio
async def test_chain_raises_when_every_model_fails(monkeypatch) -> None:
    cfg = _cfg("a", "b", timeout=10)

    async def fake_post(url, payload, timeout, headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("fleeting.services.llm._post_chat", fake_post)

    with pytest.raises(LLMUnavailable):
        await enrich_chain("text", cfg)


@pytest.mark.anyio
async def test_unparseable_output_moves_to_the_next_model(monkeypatch) -> None:
    """Garbage is a failure for this step, not for the whole chain."""
    cfg = _cfg("chatty", "terse", timeout=10)

    async def fake_post(url, payload, timeout, headers=None):
        if payload["model"] == "chatty":
            return "I think the title might be something like...?"
        return '{"title": "t", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr("fleeting.services.llm._post_chat", fake_post)

    out = await enrich_chain("text", cfg)
    assert out["title"] == "t"


@pytest.mark.anyio
async def test_a_single_model_chain_behaves_like_enrich(monkeypatch) -> None:
    cfg = _cfg("solo", timeout=10)
    seen: list[dict] = []

    async def fake_post(url, payload, timeout, headers=None):
        seen.append(payload)
        return '{"title": "t", "summary": "s", "tags": ["x"], "action_items": []}'

    monkeypatch.setattr("fleeting.services.llm._post_chat", fake_post)

    out = await enrich_chain("capture me", cfg, prompt="template hint")
    assert out["tags"] == ["x"]
    assert "template hint" in seen[0]["messages"][0]["content"]
