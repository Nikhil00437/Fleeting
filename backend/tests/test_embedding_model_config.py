"""#92 wiring: a dedicated embedding model, and one resolver for its name.

Covers the two failures that make a misconfigured embedding setup invisible:
the name being resolved in two places that disagree, and a legal provider
("custom") that silently fell through to the offline vectorizer.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fleeting.config import LLMConfig
from fleeting.services.embedding_model import resolve_embedding_model
from fleeting.services.embedding_prompt import (
    DOCUMENT_PREFIX,
    QUERY_PREFIX,
    embedding_payload,
    is_task_prompt_model,
)


# ---- the resolver --------------------------------------------------------


def test_a_dedicated_embedding_model_wins() -> None:
    cfg = LLMConfig(provider="ollama", model="chat-model", embedding_model="embed-model")
    assert resolve_embedding_model(cfg) == "embed-model"


def test_without_one_the_general_model_is_used() -> None:
    """Existing configs set only `model`; they must keep working unchanged."""
    cfg = LLMConfig(provider="ollama", model="nomic-embed-text")
    assert resolve_embedding_model(cfg) == "nomic-embed-text"


def test_a_blank_embedding_model_falls_back() -> None:
    """Settings fields are cleared to "", which must not mean "no model"."""
    cfg = LLMConfig(provider="ollama", model="m", embedding_model="   ")
    assert resolve_embedding_model(cfg) == "m"


def test_the_provider_default_is_used_when_nothing_is_set() -> None:
    assert resolve_embedding_model(LLMConfig(provider="ollama")) == "nomic-embed-text"


def test_lmstudio_gets_its_own_default() -> None:
    assert resolve_embedding_model(LLMConfig(provider="lmstudio")) == "text-embedding-3-small"


def test_custom_gets_an_openai_compatible_default() -> None:
    assert resolve_embedding_model(LLMConfig(provider="custom")) == "text-embedding-3-small"


def test_the_resolver_never_returns_an_empty_string() -> None:
    """An empty name would make every stored row compare as stale, forever."""
    for provider in ("ollama", "lmstudio", "custom", "none", ""):
        assert resolve_embedding_model(LLMConfig(provider=provider))


# ---- task prompts --------------------------------------------------------


def test_the_model_is_recognised_with_and_without_a_tag() -> None:
    assert is_task_prompt_model("embeddinggemma-2")
    assert is_task_prompt_model("embeddinggemma-2:270m")


def test_the_lm_studio_filename_convention_is_recognised() -> None:
    """LM Studio exposes the file as text-embedding-<model>.gguf.

    Without this the prefixes silently do not apply and every search returns
    noise — no error, no warning, just worse results.
    """
    assert is_task_prompt_model("text-embedding-embeddinggemma-2.gguf")


def test_an_ordinary_model_needs_no_prefix() -> None:
    assert not is_task_prompt_model("nomic-embed-text")


def test_a_query_gets_the_query_prefix() -> None:
    out = embedding_payload("router firmware", "embeddinggemma-2", kind="query")
    assert out.startswith(QUERY_PREFIX)
    assert "router firmware" in out


def test_a_document_gets_its_real_title() -> None:
    """The model's document prefix has a title slot saying 'none'."""
    out = embedding_payload(
        "the body text", "embeddinggemma-2", kind="document", title="Router notes"
    )
    assert out.startswith(DOCUMENT_PREFIX.format(title="Router notes"))
    assert "the body text" in out


def test_a_document_with_no_title_says_none() -> None:
    out = embedding_payload("body", "embeddinggemma-2", kind="document")
    assert out.startswith(DOCUMENT_PREFIX.format(title="none"))


def test_an_untrained_model_gets_bare_text() -> None:
    """A prefix on a model that never saw one is just noise."""
    assert embedding_payload("q", "nomic-embed-text", kind="query") == "q"
    assert embedding_payload("d", "nomic-embed-text", kind="document", title="T") == "d"


def test_a_query_and_a_document_are_pushed_apart() -> None:
    """The whole point: same words, different spaces."""
    q = embedding_payload("router", "embeddinggemma-2", kind="query")
    d = embedding_payload("router", "embeddinggemma-2", kind="document", title="Router")
    assert q != d


# ---- the provider gap ----------------------------------------------------


@pytest.mark.anyio
async def test_custom_provider_reaches_the_openai_compatible_endpoint(
    monkeypatch,
) -> None:
    """`custom` is a legal provider but fell through to the offline vectorizer."""
    from fleeting.services import embeddings

    seen: list[dict] = []

    def fake_post(self, url, json=None, **kw):
        seen.append({"url": url, "json": json})
        resp = httpx.Response(
            200,
            json={"data": [{"embedding": [0.0, 3.0, 4.0]}]},
            request=httpx.Request("POST", url),
        )
        return resp

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    from fleeting.config import Config

    cfg = Config()
    cfg.llm.provider = "custom"
    cfg.llm.base_url = "http://x:8080"
    cfg.llm.model = "eg2"
    vec, model = embeddings.embed_text_with_model("hello", cfg)

    assert seen, "custom provider never issued a request"
    assert "/v1/embeddings" in seen[0]["url"]
    assert vec == [0.0, 0.6, 0.8], "vectors must still be unit-normalised"
    assert model == "eg2"


@pytest.mark.anyio
async def test_an_openai_compatible_model_gains_its_prefix(monkeypatch) -> None:
    from fleeting.config import Config
    from fleeting.services import embeddings

    sent: list[dict] = []

    def fake_post(self, url, json=None, **kw):
        sent.append(json or {})
        return httpx.Response(
            200,
            json={"data": [{"embedding": [1.0, 0.0]}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    cfg = Config()
    cfg.llm.provider = "custom"
    cfg.llm.base_url = "http://x:8080"
    cfg.llm.model = "embeddinggemma-2"

    embeddings.embed_text("router firmware", cfg, kind="query")
    assert sent[0]["input"].startswith(QUERY_PREFIX)


@pytest.mark.anyio
async def test_ollama_documents_gain_their_prefix(monkeypatch) -> None:
    from fleeting.config import Config
    from fleeting.services import embeddings

    sent: list[dict] = []

    def fake_post(self, url, json=None, **kw):
        sent.append(json or {})
        return httpx.Response(
            200,
            json={"embedding": [1.0, 0.0]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://x:11434"
    cfg.llm.embedding_model = "embeddinggemma-2"

    embeddings.embed_text("the body", cfg, kind="document", title="Router notes")
    assert sent[0]["prompt"].startswith("title: Router notes | text:")

# ---- where the embedding request goes -------------------------------------
#
# Chat and embedding are different resources: a 9B chat model and a 300M
# embedder are usually on different servers, and one of them is often a
# desktop app that gets closed. Forcing them to share an endpoint means
# closing LM Studio takes chat down too, so embeddings may name their own.


def _cfg(provider: str = "custom") -> LLMConfig:
    cfg = LLMConfig(provider=provider, model="chat-model", embedding_model="embed-model")
    cfg.base_url = "http://127.0.0.1:11434"
    return cfg


def test_embeddings_go_to_the_shared_url_by_default(monkeypatch) -> None:
    from fleeting.services.embeddings import embed_text_with_model

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_text_with_model("hello", _as_app(_cfg_with()))
    assert seen[0].startswith("http://127.0.0.1:11434/v1/embeddings")


def test_a_dedicated_embedding_url_overrides_the_shared_one(monkeypatch) -> None:
    from fleeting.services.embeddings import embed_text_with_model

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_text_with_model("hello", _as_app(_cfg_with(embedding_base_url="http://127.0.0.1:1234")))
    assert seen[0].startswith("http://127.0.0.1:1234/v1/embeddings")


def test_the_batched_path_honours_the_same_override(monkeypatch) -> None:
    from fleeting.config import Config
    from fleeting.services.embedding_batch import embed_batch

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_batch(["a"], _as_app(_cfg_with(embedding_base_url="http://127.0.0.1:1234")))
    assert seen[0].startswith("http://127.0.0.1:1234/v1/embeddings")


def test_an_embedding_request_is_not_capped_at_the_chat_timeout(monkeypatch) -> None:
    """The 5s cap that keeps chat responsive breaks a cold model load.

    LM Studio pays the entire load on the first request after an idle unload.
    An intermittent timeout is worse than a slow one: it silently falls back
    to hash vectors, so the index looks healthy and searches are lexical.
    """
    from fleeting.services.embeddings import embed_text_with_model

    cfg = _cfg_with()
    cfg.timeout_secs = 60
    seen: list[float] = []
    _capture_posts(monkeypatch, [], timeouts=seen)
    embed_text_with_model("hello", _as_app(cfg))
    assert seen[0] >= 30.0, f"embedding timeout was clamped to {seen[0]}s"


# ---- helpers --------------------------------------------------------------


def _cfg_with(**kw) -> "object":
    """An LLMConfig shaped like a real one, with overrides applied."""
    cfg = _cfg()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def _as_app(llm: LLMConfig):
    from fleeting.config import Config

    cfg = Config()
    cfg.llm = llm
    return cfg


def _capture_posts(
    monkeypatch, urls: list[str], timeouts: list[float] | None = None
) -> None:
    """Record the endpoint (and optionally the timeout) each request uses."""
    real_init = httpx.Client.__init__

    def init(self, *a, **kw):
        if timeouts is not None and "timeout" in kw:
            timeouts.append(float(kw["timeout"]))
        return real_init(self, *a, **kw)

    def post(self, url, json=None, **kw):
        urls.append(str(url))
        n = len(json.get("input", [])) if isinstance(json.get("input"), list) else 1
        return httpx.Response(
            200,
            json={"data": [{"embedding": [1.0] * 4} for _ in range(n)]},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.Client, "__init__", init)
    monkeypatch.setattr(httpx.Client, "post", post)


# ---- the embedding server's dialect ---------------------------------------
#
# LM Studio answers Ollama's /api/embeddings with HTTP 200 and an
# {"error": ...} body, so a wrong dialect is not a crash -- it is a silent
# fall back to hash vectors. The dialect has to be selectable independently of
# the provider that serves chat, or pointing embeddings at a second server
# cannot work at all.


def test_a_second_server_may_speak_the_openai_dialect(monkeypatch) -> None:
    from fleeting.services.embeddings import embed_text_with_model

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_text_with_model(
        "hello",
        _as_app(
            _cfg_with(
                provider="ollama",
                embedding_provider="custom",
                embedding_base_url="http://127.0.0.1:1234",
            )
        ),
    )
    assert seen[0] == "http://127.0.0.1:1234/v1/embeddings"


def test_without_an_embedding_provider_the_shared_one_still_applies(monkeypatch) -> None:
    from fleeting.services.embeddings import embed_text_with_model

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_text_with_model("hello", _as_app(_cfg_with(provider="ollama")))
    assert seen[0].endswith("/api/embeddings")


def test_the_batched_path_uses_the_same_dialect(monkeypatch) -> None:
    from fleeting.services.embedding_batch import embed_batch

    seen: list[str] = []
    _capture_posts(monkeypatch, seen)
    embed_batch(
        ["a"],
        _as_app(
            _cfg_with(
                provider="ollama",
                embedding_provider="custom",
                embedding_base_url="http://127.0.0.1:1234",
            )
        ),
    )
    assert seen[0] == "http://127.0.0.1:1234/v1/embeddings"


def test_a_two_hundred_with_an_error_body_is_not_a_success(
    monkeypatch, caplog
) -> None:
    """LM Studio returns HTTP 200 plus {"error": ...}.

    Without this the vector silently becomes local-hash-384 and the index
    looks healthy while every search is lexical-only.
    """
    from fleeting.services.embeddings import embed_text_with_model

    real_init = httpx.Client.__init__

    def init(self, *a, **kw):
        return real_init(self, *a, **kw)

    def post(self, url, json=None, **kw):
        return httpx.Response(
            200,
            json={"error": "unknown model"},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.Client, "__init__", init)
    monkeypatch.setattr(httpx.Client, "post", post)

    vec, model = embed_text_with_model("hello", _as_app(_cfg_with()))
    assert model == "local-hash-384"
    assert len(vec) == 384
    # The degradation must be visible: this is the whole reason the health
    # panel exists, and an unlogged fallback means the user never learns.
    assert any("falling back" in r.message for r in caplog.records), [
        r.message for r in caplog.records
    ]
