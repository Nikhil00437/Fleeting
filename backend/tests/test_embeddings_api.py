"""The embedding migration must be reachable and observable from the API.

Turning the LLM on changes the embedding dimensionality, and vectors of
different lengths cannot be compared — so notes captured before the switch stop
appearing in semantic search. PR 1 made the app *report* the stale count; this
is the other half: a way to actually fix it, and visible progress while it runs.
"""

from __future__ import annotations

import json
import time

import pytest

import fleeting.services.embeddings as femb
from fleeting.services.embeddings import LocalHashVectorizer, pack_vector


def _wait(client, timeout: float = 5.0) -> None:
    """Block until the background migration clears itself.

    The endpoint is deliberately fire-and-forget, so tests must wait for the
    task rather than assume it finished. `backfill_task` is set to None in the
    task's `finally`, which makes it the completion signal.
    """
    st = client.app.state.st
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if st.backfill_task is None:
            return
        time.sleep(0.02)
    raise AssertionError("embedding backfill did not finish in time")


def _seed(client, count: int = 3, model: str = "local-hash-384", dims: int = 384) -> list[str]:
    db = client.app.state.st.db
    ids = []
    for i in range(count):
        note = db.insert_note({"raw_text": f"stale note {i}", "type": "text"})
        nid = note["id"] if isinstance(note, dict) else note
        base = LocalHashVectorizer().embed(f"stale note {i}")
        vec = (base + [0.0] * dims)[:dims]
        db.upsert_note_embedding(nid, pack_vector(vec), len(vec), model)
        ids.append(nid)
    return ids


def _use_ollama(client, model: str = "nomic-embed-text") -> None:
    st = client.app.state.st
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = model


@pytest.fixture
def fake_embed(monkeypatch):
    """Stand in for the HTTP embedding call."""
    calls: list[str] = []

    def fake(text: str, cfg=None):
        calls.append(text)
        return [0.3] * 768, "nomic-embed-text"

    monkeypatch.setattr(femb, "embed_text_with_model", fake)
    return calls


def test_backfill_endpoint_migrates_the_corpus(client, fake_embed) -> None:
    ids = _seed(client, 4)
    _use_ollama(client)

    r = client.post("/api/settings/embeddings/backfill")

    assert r.status_code == 200
    assert r.json()["started"] is True
    _wait(client)
    st = client.app.state.st
    for nid in ids:
        row = st.db.get_note_embedding(nid)
        assert row["model"] == "nomic-embed-text"
        assert row["dimensions"] == 768


def test_backfill_endpoint_reports_a_second_call_as_busy(client, fake_embed) -> None:
    _seed(client, 2)
    _use_ollama(client)
    first = client.post("/api/settings/embeddings/backfill").json()
    assert first["started"] is True
    second = client.post("/api/settings/embeddings/backfill").json()
    assert second["started"] is False
    assert second["reason"] == "already running"


def test_backfill_publishes_progress_events(client, fake_embed) -> None:
    _seed(client, 3)
    _use_ollama(client)
    st = client.app.state.st

    seen: list[str] = []
    payloads: list[dict] = []
    queue = st.bus.subscribe()

    client.post("/api/settings/embeddings/backfill")
    _wait(client)
    while not queue.empty():  # the work ran in a worker thread; drain what it published
        event = json.loads(queue.get_nowait())
        seen.append(event["type"])
        if event["type"] == "embedding.backfill.progress":
            payloads.append(event["data"])

    assert "embedding.backfill.progress" in seen, f"no progress events: {seen}"
    # and a finished marker so the UI can stop the spinner
    assert any(d.get("finished") for d in payloads), "never signalled completion"
    assert any(d.get("started") for d in payloads), "never signalled a total"


def test_backfill_skips_work_when_nothing_is_stale(client, fake_embed) -> None:
    _seed(client, 2, model="nomic-embed-text", dims=768)
    _use_ollama(client)

    r = client.post("/api/settings/embeddings/backfill")

    assert r.status_code == 200
    assert fake_embed == [], "re-embedded a corpus that was already current"


def test_backfill_is_skipped_without_an_llm(client, fake_embed) -> None:
    _seed(client, 2)
    st = client.app.state.st
    st.cfg.llm.provider = "none"

    client.post("/api/settings/embeddings/backfill")

    assert fake_embed == [], "ran a migration with no LLM to embed with"


def test_health_stale_count_drops_after_migration(client, fake_embed) -> None:
    _seed(client, 3)
    _use_ollama(client)

    before = client.get("/api/health").json()
    assert before["stale_embeddings"] == 3
    assert any("still use the old embedding model" in d for d in before["degradations"])

    client.post("/api/settings/embeddings/backfill")
    _wait(client)

    after = client.get("/api/health").json()
    assert after["stale_embeddings"] == 0
    assert not any("old embedding model" in d for d in after["degradations"])
    assert after["semantic_search"] == "semantic"
