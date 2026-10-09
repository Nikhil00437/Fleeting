"""#92 a model per task.

Tags want a small fast model; reports want the big one. Without this every
call uses one model, which is either slow on capture or bad at writing.

A role with no override uses the configured model, so this is opt-in per
role and an empty config behaves exactly as before.
"""

from __future__ import annotations

import httpx
import pytest

from fleeting.config import Config, LLMConfig
from fleeting.services import llm as llm_svc


def test_no_overrides_means_one_model_everywhere() -> None:
    cfg = LLMConfig(provider="ollama", model="big")
    assert llm_svc.model_for(cfg, "enrich") == "big"
    assert llm_svc.model_for(cfg, "report") == "big"
    assert llm_svc.model_for(cfg, "assistant") == "big"


def test_a_role_override_wins() -> None:
    cfg = LLMConfig(provider="ollama", model="big", enrich_model="small")
    assert llm_svc.model_for(cfg, "enrich") == "small"
    assert llm_svc.model_for(cfg, "report") == "big"


def test_a_blank_override_falls_back() -> None:
    """An emptied settings field must not mean 'no model'."""
    cfg = LLMConfig(provider="ollama", model="big", enrich_model="   ")
    assert llm_svc.model_for(cfg, "enrich") == "big"


def test_an_unknown_role_falls_back() -> None:
    cfg = LLMConfig(provider="ollama", model="big")
    assert llm_svc.model_for(cfg, "transcribe") == "big"


def test_config_exposes_the_three_roles() -> None:
    cfg = Config()
    assert cfg.llm.report_model == ""
    assert cfg.llm.assistant_model == ""


def test_overrides_round_trip_through_config(tmp_path, monkeypatch) -> None:
    import fleeting.config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = Config()
    cfg.llm.model = "big"
    cfg.llm.enrich_model = "small"
    fcfg.save_config(cfg)

    loaded = fcfg.load_config()
    assert loaded.llm.enrich_model == "small"
    assert loaded.llm.model == "big"


@pytest.mark.anyio
async def test_the_enrichment_chain_starts_at_the_role_model(monkeypatch) -> None:
    cfg = LLMConfig(provider="ollama", model="big", enrich_model="small", timeout_secs=10)
    seen: list[dict] = []

    async def fake(url, payload, timeout, headers=None):
        seen.append(payload)
        return '{"title": "t", "summary": "s", "tags": [], "action_items": []}'

    monkeypatch.setattr(llm_svc, "_post_chat", fake)
    await llm_svc.enrich_chain("text", cfg)

    assert seen[0]["model"] == "small"


@pytest.mark.anyio
async def test_the_role_model_still_gets_a_fallback_chain(monkeypatch) -> None:
    """Picking a small model for tags must not cost it its fallback."""
    cfg = LLMConfig(
        provider="ollama", model="big", enrich_model="small",
        fallback_models="tiny", timeout_secs=10,
    )
    tried: list[str] = []

    async def fake(url, payload, timeout, headers=None):
        tried.append(payload["model"])
        raise httpx.ConnectError("down")

    monkeypatch.setattr(llm_svc, "_post_chat", fake)
    with pytest.raises(llm_svc.LLMUnavailable):
        await llm_svc.enrich_chain("text", cfg)

    # The chain is the role model first, then the shared fallbacks.
    assert tried == ["small", "tiny"]


def test_the_digest_uses_the_report_model() -> None:
    from fleeting.services.dailylog import generate_with_llm

    cfg = LLMConfig(provider="ollama", model="big", report_model="writer")
    assert llm_svc.model_for(cfg, "report") == "writer"
