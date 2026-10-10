"""Batched embedding: one request for many notes, and a live end-to-end check."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services import embedding_batch as eb


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _cfg(provider: str = "custom", model: str = "text-embedding-embeddinggemma-2") -> Config:
    cfg = Config()
    cfg.llm.provider = provider
    cfg.llm.base_url = "http://127.0.0.1:1234"
    cfg.llm.embedding_model = model
    return cfg


def _capture(monkeypatch, vectors: list[list[float]]) -> list[dict]:
    seen: list[dict] = []

    def fake_post(self, url, json=None, **kw):
        seen.append({"url": url, "json": json})
        n = len(json.get("input", []))
        return httpx.Response(
            200,
            json={"data": [{"embedding": v} for v in vectors[:n]]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    return seen


# ---- extraction ----------------------------------------------------------


def test_the_openai_shape_is_understood(monkeypatch) -> None:
    seen = _capture(monkeypatch, [[3.0, 4.0]] * 2)
    out = eb.embed_batch(["a", "b"], _cfg())
    assert seen[0]["url"].endswith("/v1/embeddings")
    assert out == [[0.6, 0.8], [0.6, 0.8]]


def test_the_ollama_shape_is_understood(monkeypatch) -> None:
    seen: list[dict] = []

    def fake_post(self, url, json=None, **kw):
        seen.append({"url": url, "json": json})
        return httpx.Response(
            200,
            json={"embeddings": [[3.0, 4.0]] * len(json["input"])},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    out = eb.embed_batch(["a", "b"], _cfg(provider="ollama"))
    assert seen[0]["url"].endswith("/api/embed")
    assert out[0] == [0.6, 0.8]


def test_a_short_response_is_padded_with_nones(monkeypatch) -> None:
    """A truncated reply must not silently mis-pair vectors with notes."""
    _capture(monkeypatch, [[1.0, 0.0]])
    out = eb.embed_batch(["a", "b", "c"], _cfg())
    assert out == [[1.0, 0.0], None, None]


def test_each_note_keeps_its_own_title(monkeypatch) -> None:
    seen = _capture(monkeypatch, [[1.0]] * 2)
    eb.embed_batch(["body one", "body two"], _cfg(), titles=["First", "Second"])
    inputs = seen[0]["json"]["input"]
    assert "title: First" in inputs[0]
    assert "title: Second" in inputs[1]


def test_a_transport_failure_costs_only_this_batch(monkeypatch) -> None:
    def boom(self, url, json=None, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.Client, "post", boom)
    assert eb.embed_batch(["a", "b"], _cfg()) == [None, None]


def test_no_provider_yields_nones_without_a_request(monkeypatch) -> None:
    seen = _capture(monkeypatch, [[1.0]])
    cfg = _cfg()
    cfg.llm.provider = "none"
    assert eb.embed_batch(["a"], cfg) == [None]
    assert seen == []


def test_an_empty_batch_is_not_a_request(monkeypatch) -> None:
    seen = _capture(monkeypatch, [[1.0]])
    assert eb.embed_batch([], _cfg()) == []
    assert seen == []


# ---- the corpus ----------------------------------------------------------


def test_reembedding_covers_every_active_note(db: Database, monkeypatch) -> None:
    _capture(monkeypatch, [[1.0, 2.0, 3.0]] * 6)
    for i in range(6):
        db.insert_note({"title": f"n{i}", "raw_text": f"body {i}", "status": "done"})

    done = eb.reembed_corpus(db, _cfg())
    assert done == 6
    assert db.count_stale_embeddings("text-embedding-embeddinggemma-2") == 0


def test_reembedding_skips_trashed_and_archived(db: Database, monkeypatch) -> None:
    _capture(monkeypatch, [[1.0]] * 4)
    keep = db.insert_note({"title": "keep", "raw_text": "body", "status": "done"})
    db.insert_note({"title": "gone", "raw_text": "body", "status": "done", "archived": 1})
    db.execute("UPDATE notes SET trashed_at = '2026-01-01' WHERE title = 'keep'")
    db.commit()

    eb.reembed_corpus(db, _cfg())
    assert db.get_note(keep["id"]) is not None


def test_reembedding_reports_progress(db: Database, monkeypatch) -> None:
    _capture(monkeypatch, [[1.0]] * 4)
    for i in range(4):
        db.insert_note({"title": f"n{i}", "raw_text": f"body {i}", "status": "done"})
    seen: list[int] = []
    eb.reembed_corpus(db, _cfg(), batch=2, on_progress=seen.append)
    assert seen and seen[-1] == 4