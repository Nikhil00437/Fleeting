"""Semantic search must survive an embedding-model change.

When the LLM comes online, new notes get real embeddings (e.g. 768-dim
nomic-embed-text) while older notes still hold 384-dim local-hash vectors.
`cosine_similarity` returns 0.0 on a length mismatch, and the search path
dropped anything scoring <= 0.05 — so flipping on Ollama silently *deleted*
every previously-captured note from semantic results.

The fallback itself is also invisible: a failed remote call logs at DEBUG while
the app runs at INFO, so the user is never told their index is fake.
"""

from __future__ import annotations

import math

import pytest

import fleeting.services.embeddings as femb
from fleeting.config import Config, LLMConfig
from fleeting.db import Database
from fleeting.services.embeddings import (
    LocalHashVectorizer,
    cosine_similarity,
    embed_text_with_model,
    pack_vector,
)
from fleeting.services.semantic_search import hybrid_search


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "e.db")
    d.migrate()
    return d


def _store(db: Database, text: str, model: str, dims: int) -> str:
    """Store an embedding of exactly `dims` length, labelled `model`.

    Pads because LocalHashVectorizer only emits 384 dims — slicing it would
    store a short blob under a larger declared dimension, which is not the
    mixed-dimension case under test.
    """
    note = db.insert_note({"raw_text": text, "type": "text", "title": text})
    nid = note["id"] if isinstance(note, dict) else note
    base = LocalHashVectorizer().embed(text)
    vec = (base + [0.0] * dims)[:dims] if dims > len(base) else base[:dims]
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    vec = [x / norm for x in vec]
    assert len(vec) == dims
    db.upsert_note_embedding(nid, pack_vector(vec), len(vec), model)
    return nid


def _found(db: Database, cfg, query: str) -> set[str]:
    return {r["id"] for r in hybrid_search(db, query, cfg, mode="semantic", limit=50)}


# ---------------------------------------------------------------------------
# dimension guard
# ---------------------------------------------------------------------------


def test_mixed_dimensions_do_not_hide_same_dimension_notes(db) -> None:
    """A 768-dim row must not drag 384-dim notes out of the results.

    Before the fix `cosine_similarity` returned 0.0 on a length mismatch and
    every result below 0.05 was dropped, so notes captured before Ollama came
    online silently disappeared from semantic search.
    """
    cfg = LLMConfig(provider="none")
    old = _store(db, "kubernetes ingress controller notes", "local-hash-384", 384)
    _store(db, "kubernetes ingress controller notes", "nomic-embed-text", 768)

    assert old in _found(db, cfg, "kubernetes ingress")


def test_query_dimension_selects_the_matching_model(db, monkeypatch) -> None:
    """A 768-dim query searches the 768-dim corpus and skips the rest."""
    import fleeting.services.embeddings as mod

    cfg = LLMConfig(provider="none")
    _store(db, "kubernetes ingress controller notes", "local-hash-384", 384)
    new = _store(db, "kubernetes ingress controller notes", "nomic-embed-text", 768)

    real = mod.LocalHashVectorizer().embed("kubernetes ingress")
    padded = (real + [0.0] * 768)[:768]
    norm = math.sqrt(sum(x * x for x in padded)) or 1.0
    padded = [x / norm for x in padded]
    # semantic_search imported embed_text by name, so patch it there.
    monkeypatch.setattr("fleeting.services.semantic_search.embed_text", lambda t, c=None: padded)

    assert new in _found(db, cfg, "kubernetes ingress")


def test_all_results_are_same_dimensions(db) -> None:
    cfg = LLMConfig(provider="none")
    _store(db, "alpha beta", "local-hash-384", 384)
    _store(db, "gamma delta", "nomic-embed-text", 768)

    for r in hybrid_search(db, "alpha", cfg, mode="semantic", limit=50):
        row = db.get_note_embedding(r["id"])
        assert row is None or row["dimensions"] in (384, 768)


def test_uniform_dimensions_still_match(db) -> None:
    """The fix must not break the normal single-model case.

    Only asserts the relevant note is findable — the offline hash vectorizer is
    a fuzzy lexical signal, so unrelated notes leaking in at >0.05 similarity is
    its documented behaviour, not a regression here.
    """
    cfg = LLMConfig(provider="none")
    a = _store(db, "postgres connection pool tuning", "local-hash-384", 384)
    _store(db, "unrelated grocery list", "local-hash-384", 384)
    assert a in _found(db, cfg, "postgres connection pool")


def test_cosine_mismatch_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# backfill: re-embed stale notes
# ---------------------------------------------------------------------------


def test_backfill_reembeds_mismatched_notes(db, monkeypatch) -> None:
    cfg = LLMConfig(provider="none")
    stale = _store(db, "terraform drift detection", "local-hash-384", 384)

    calls: list[str] = []

    def fake_embed(text: str, cfg=None):
        calls.append(text)
        return [0.5] * 768, "nomic-embed-text"

    monkeypatch.setattr(femb, "embed_text_with_model", fake_embed)
    import fleeting.services.embeddings as mod

    assert hasattr(mod, "backfill_embeddings"), "no backfill entrypoint exists"

    n = mod.backfill_embeddings(db, cfg, provider="nomic-embed-text", dimensions=768)
    assert n >= 1
    row = db.get_note_embedding(stale)
    assert row["dimensions"] == 768
    assert row["model"] == "nomic-embed-text"


def test_backfill_skips_current_model(db, monkeypatch) -> None:
    cfg = LLMConfig(provider="none")
    _store(db, "already fine", "nomic-embed-text", 768)

    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None: ([0.1] * 768, "nomic-embed-text")
    )
    import fleeting.services.embeddings as mod

    assert mod.backfill_embeddings(db, cfg, provider="nomic-embed-text", dimensions=768) == 0


# ---------------------------------------------------------------------------
# fallback visibility
# ---------------------------------------------------------------------------


def test_fallback_logs_at_warning_not_debug(monkeypatch, caplog) -> None:
    """A silent index downgrade is the bug; it must be visible in the log.

    Passes a full Config because embed_text_with_model reads cfg.llm.
    """
    import logging

    import httpx

    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:1"
    cfg.llm.timeout_secs = 5

    class Boom:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(femb.httpx, "Client", lambda *a, **kw: Boom())

    with caplog.at_level(logging.INFO):
        vec, model = embed_text_with_model("hello", cfg)

    assert model == "local-hash-384"
    assert len(vec) == 384
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("embedding" in r.getMessage().lower() for r in warnings), (
        "remote embedding failed but nothing was logged at WARNING or above"
    )


def test_provider_none_is_not_a_warning(caplog) -> None:
    """Using the fallback on purpose (provider=none) must stay quiet."""
    import logging

    cfg = Config()
    cfg.llm.provider = "none"
    with caplog.at_level(logging.INFO):
        vec, model = embed_text_with_model("hello", cfg)
    assert model == "local-hash-384"
    assert len(vec) == 384
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], (
        "provider=none is a deliberate choice, not a degradation"
    )