"""#95 "reprocess everything" after a model or dimension change.

Two things have to be true for this to be worth running on a whole corpus.
Progress, because it is slow and the UI must show it moving. And an explicit
line between the two halves: re-embedding is derived data and always safe to
redo, while re-running enrichment overwrites the title, summary and tags the
user may have been editing all afternoon.

Nothing here guesses which half is wanted. Re-embedding is the default;
overwriting the user's words requires a confirm.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.reprocess import reprocess_corpus


@pytest.fixture
def env(tmp_path: Path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    cfg.paths.vault_dir = str(tmp_path / "vault")
    return db, cfg, EventBus()


def _note(db: Database, title: str, body: str, **kw) -> str:
    return db.insert_note({"title": title, "raw_text": body, "status": "done", **kw})["id"]


# ---- the default is the safe half ----------------------------------------


@pytest.mark.anyio
async def test_reembedding_does_not_touch_the_user_s_words(env, monkeypatch) -> None:
    """Titles and summaries are the user's, however they got there."""
    db, cfg, bus = env
    nid = _note(db, "my own title", "some body text", summary="my own summary")
    monkeypatch.setattr(
        "fleeting.services.embedding_batch.reembed_corpus", lambda *a, **k: 1
    )

    out = await reprocess_corpus(db, cfg, bus, scope="embeddings")

    assert out["reembedded"] == 1
    note = db.get_note(nid)
    assert note["title"] == "my own title"
    assert note["summary"] == "my own summary"


@pytest.mark.anyio
async def test_enrichment_requires_an_explicit_confirm(env) -> None:
    db, cfg, bus = env
    nid = _note(db, "a title", "a body")

    out = await reprocess_corpus(db, cfg, bus, scope="everything", confirm=False)

    assert out["ok"] is False
    assert "confirm" in out["error"].lower()
    assert db.get_note(nid)["title"] == "a title"


@pytest.mark.anyio
async def test_enrichment_refuses_without_an_llm(env) -> None:
    db, cfg, bus = env
    _note(db, "a title", "a body")
    cfg.llm.provider = "none"

    out = await reprocess_corpus(db, cfg, bus, scope="everything", confirm=True)

    assert out["ok"] is False
    assert "llm" in out["error"].lower()


@pytest.mark.anyio
async def test_an_unknown_scope_is_refused(env) -> None:
    db, cfg, bus = env
    out = await reprocess_corpus(db, cfg, bus, scope="titles")
    assert out["ok"] is False


# ---- progress ------------------------------------------------------------


@pytest.mark.anyio
async def test_progress_is_published_including_the_total(env, monkeypatch) -> None:
    db, cfg, bus = env
    for i in range(3):
        _note(db, f"n{i}", "body")
    monkeypatch.setattr(
        "fleeting.services.embedding_batch.reembed_corpus", lambda *a, **k: 3
    )
    events: list[dict] = []
    bus.subscribe("reprocess.progress", lambda d: events.append(d))

    await reprocess_corpus(db, cfg, bus, scope="embeddings")

    assert events
    assert events[0]["done"] == 0
    assert events[0]["total"] > 0
    assert events[-1].get("finished") is True


@pytest.mark.anyio
async def test_an_unreachable_embedder_reports_zero_not_done(env) -> None:
    """Reporting done == total with nothing moved would read as a real pass."""
    db, cfg, bus = env
    _note(db, "one", "body")
    cfg.llm.provider = "none"
    events: list[dict] = []
    bus.subscribe("reprocess.progress", lambda d: events.append(d))

    out = await reprocess_corpus(db, cfg, bus, scope="embeddings")

    assert out["reembedded"] == 0
    assert events[-1].get("finished") is True
    assert events[-1].get("reembedded") == 0


# ---- scope ---------------------------------------------------------------


@pytest.mark.anyio
async def test_reembedding_covers_every_active_note(env, monkeypatch) -> None:
    db, cfg, bus = env
    keep = _note(db, "live", "body")
    db.update_note(_note(db, "archived one", "body"), {"archived": 1})
    trashed = _note(db, "trashed one", "body")
    db.execute("UPDATE notes SET trashed_at = '2026-01-01' WHERE id = ?", (trashed,))
    db.commit()
    seen: list[str] = []

    def fake(db_, cfg_, **kw):
        seen.extend(
            [r["id"] for r in db_.execute(
                "SELECT id FROM notes WHERE trashed_at IS NULL AND archived = 0"
            )]
        )
        return len(seen)

    monkeypatch.setattr("fleeting.services.embedding_batch.reembed_corpus", fake)

    await reprocess_corpus(db, cfg, bus, scope="embeddings")

    assert seen == [keep]


@pytest.mark.anyio
async def test_a_note_with_no_content_is_skipped(env, monkeypatch) -> None:
    """An empty note has nothing to enrich, and must not spend the call."""
    db, cfg, bus = env
    _note(db, "empty", "")
    seen: list[str] = []
    monkeypatch.setattr(
        "fleeting.services.embedding_batch.reembed_corpus", lambda *a, **k: 0
    )

    async def fake_enrich(text, cfg, **kw):
        seen.append(text)
        return {"title": "t", "summary": "s", "tags": ["a"]}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    out = await reprocess_corpus(db, cfg, bus, scope="everything", confirm=True)

    assert seen == []
    assert out["enriched"] == 0


@pytest.mark.anyio
async def test_one_failing_note_does_not_abort_the_corpus(env, monkeypatch) -> None:
    db, cfg, bus = env
    _note(db, "first", "body one")
    _note(db, "second", "body two")
    monkeypatch.setattr(
        "fleeting.services.embedding_batch.reembed_corpus", lambda *a, **k: 2
    )

    calls = {"n": 0}

    async def flaky(text, cfg, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model hiccup")
        return {"title": "t", "summary": "s", "tags": []}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", flaky)

    out = await reprocess_corpus(db, cfg, bus, scope="everything", confirm=True)

    assert out["enriched"] == 1
    assert out["failed"] == 1


@pytest.mark.anyio
async def test_enrichment_writes_the_same_fields_as_a_single_regenerate(
    env, monkeypatch
) -> None:
    """The bulk path must not be a second, subtly different, implementation."""
    db, cfg, bus = env
    nid = _note(db, "old", "body", tags=["stale-tag"])
    monkeypatch.setattr(
        "fleeting.services.embedding_batch.reembed_corpus", lambda *a, **k: 1
    )

    async def fake_enrich(text, cfg, **kw):
        return {"title": "new title", "summary": "new summary", "tags": ["fresh"]}

    monkeypatch.setattr("fleeting.services.llm.enrich_chain", fake_enrich)

    await reprocess_corpus(db, cfg, bus, scope="everything", confirm=True)

    note = db.get_note(nid)
    assert note["title"] == "new title"
    assert note["summary"] == "new summary"
    assert note["tags"] == ["fresh"]
    assert note["review_state"] == "enriched"
    # raw_text is the capture itself; a reprocess must never rewrite it.
    assert note["raw_text"] == "body"


# ---- the endpoint --------------------------------------------------------


def test_the_endpoint_defaults_to_the_safe_scope(client) -> None:
    r = client.post("/api/settings/reprocess", json={})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_the_endpoint_requires_a_confirm_to_overwrite(client) -> None:
    r = client.post("/api/settings/reprocess", json={"scope": "everything"})
    assert r.status_code == 422
    assert "confirm" in r.json()["detail"].lower()


def test_a_second_job_is_refused(client) -> None:
    client.app.state.st.reprocess_task = None
    client.post("/api/settings/reprocess", json={})
    st = client.app.state.st

    class _Done:
        @staticmethod
        def done() -> bool:
            return False

    st.reprocess_task = _Done()
    r = client.post("/api/settings/reprocess", json={})
    assert r.json()["ok"] is False
    assert "running" in r.json()["reason"]