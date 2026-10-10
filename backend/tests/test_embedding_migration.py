"""Embedding migration must actually run.

`backfill_embeddings` existed and was unit-tested, but nothing in the app ever
called it. So the sequence a real user hits is:

  1. Run with no LLM -> every note gets a 384-dim `local-hash-384` vector.
  2. Start Ollama, pick a chat model in Settings.
  3. New notes get 768-dim `nomic-embed-text` vectors.
  4. Search: every pre-Ollama note silently scores 0.0 against the new corpus
     and never appears. The old notes are not "less relevant" — they are
     *invisible*, and nothing tells the user.

Turning on the model has to migrate the corpus, or semantic search is a coin
flip on when you happened to start the app.

These tests pin the trigger and the reporting, not the HTTP call itself.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import fleeting.services.embeddings as femb
from fleeting.db import Database


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(tmp_path / "e.db")
    d.migrate()
    return d


def _note(db: Database, text: str, model: str, dims: int) -> str:
    from fleeting.services.embeddings import LocalHashVectorizer, pack_vector

    n = db.insert_note({"raw_text": text, "type": "text", "title": text})
    nid = n["id"] if isinstance(n, dict) else n
    base = LocalHashVectorizer().embed(text)
    vec = (base + [0.0] * dims)[:dims]
    db.upsert_note_embedding(nid, pack_vector(vec), len(vec), model)
    return nid


def _st(provider: str, model: str, database: Database):
    """Minimal stand-in for AppState, as _embedding_status reads it."""
    return SimpleNamespace(
        cfg=SimpleNamespace(llm=SimpleNamespace(provider=provider, model=model)),
        db=database,
    )


def test_current_embedding_model_is_reported(db: Database) -> None:
    from fleeting.routers.system import _embedding_status

    model, _ = _embedding_status(_st("ollama", "nomic-embed-text", db))
    assert model == "nomic-embed-text"


def test_stale_count_drives_the_health_degradation(db: Database) -> None:
    from fleeting.routers.system import _embedding_status

    _note(db, "old one", "local-hash-384", 384)
    _note(db, "old two", "local-hash-384", 384)
    _note(db, "fresh", "nomic-embed-text", 768)

    _, stale = _embedding_status(_st("ollama", "nomic-embed-text", db))
    assert stale == 2, "stale notes must be counted so health can warn"


# ---------------------------------------------------------------------------
# the migration itself
# ---------------------------------------------------------------------------


def test_backfill_migrates_the_whole_stale_corpus(db: Database, monkeypatch) -> None:
    from fleeting.config import Config

    ids = [_note(db, f"note {i}", "local-hash-384", 384) for i in range(5)]
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "nomic-embed-text"

    seen: list[str] = []

    def fake(text: str, cfg=None, **kw):
        seen.append(text)
        return [0.25] * 768, "nomic-embed-text"

    monkeypatch.setattr(femb, "embed_text_with_model", fake)
    n = femb.backfill_embeddings(db, cfg, provider="nomic-embed-text", dimensions=768)

    assert n == 5
    assert len(seen) == 5
    for nid in ids:
        row = db.get_note_embedding(nid)
        assert row["dimensions"] == 768
        assert row["model"] == "nomic-embed-text"


def test_backfill_is_a_noop_when_nothing_is_stale(db: Database, monkeypatch) -> None:
    from fleeting.config import Config

    _note(db, "fresh", "nomic-embed-text", 768)
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "nomic-embed-text"

    def boom(text: str, cfg=None, **kw):  # pragma: no cover - must not be called
        raise AssertionError("re-embedded a note that was already current")

    monkeypatch.setattr(femb, "embed_text_with_model", boom)
    assert femb.backfill_embeddings(db, cfg, provider="nomic-embed-text", dimensions=768) == 0


def test_backfill_skips_archived_notes(db: Database, monkeypatch) -> None:
    """An archived note is hidden from search anyway; don't pay to embed it."""
    from fleeting.config import Config

    nid = _note(db, "archived", "local-hash-384", 384)
    db.execute("UPDATE notes SET archived = 1 WHERE id = ?", (nid,))
    db.commit()

    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "nomic-embed-text"
    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None, **kw: ([0.5] * 768, "nomic-embed-text")
    )
    assert femb.backfill_embeddings(db, cfg, provider="nomic-embed-text", dimensions=768) == 0


def test_backfill_survives_one_bad_note(db: Database, monkeypatch) -> None:
    """A single failing note must not abandon the rest of the migration."""
    from fleeting.config import Config

    for i in range(3):
        _note(db, f"note {i}", "local-hash-384", 384)

    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "nomic-embed-text"

    calls = {"n": 0}

    def flaky(text: str, cfg=None, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("ollama hiccup")
        return [0.5] * 768, "nomic-embed-text"

    monkeypatch.setattr(femb, "embed_text_with_model", flaky)

    migrated = femb.backfill_embeddings(db, cfg, provider="nomic-embed-text")

    assert migrated == 2, "one bad note aborted the remaining work"
    # ...and the notes it did reach are on the new model.
    dims = {
        r["dimensions"] for r in db.execute("SELECT dimensions FROM note_embeddings").fetchall()
    }
    assert 768 in dims


def test_backfill_reports_progress_per_note(db: Database, monkeypatch) -> None:
    """A 5000-note migration needs to show something, not freeze the UI."""
    from fleeting.config import Config
    from fleeting.routers import settings as settings_router

    assert hasattr(settings_router, "backfill_embeddings_stream"), (
        "no streaming/progress entrypoint for a long migration"
    )

    for i in range(3):
        _note(db, f"note {i}", "local-hash-384", 384)
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "nomic-embed-text"
    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None, **kw: ([0.5] * 768, "nomic-embed-text")
    )

    events = []
    bus = type("B", (), {"publish": lambda self, t, d: events.append((t, d))})()
    out = settings_router.backfill_embeddings_stream(db, cfg, bus)
    assert out["migrated"] == 3
    assert any(t == "embedding.backfill.progress" for t, _ in events), (
        f"no progress events published: {events}"
    )


@pytest.mark.anyio
async def test_boot_schedules_a_backfill_when_the_corpus_is_stale(client, monkeypatch) -> None:
    """The whole point: switching models must migrate without being asked."""
    import fleeting.services.embeddings as mod

    st = client.app.state.st
    _note(st.db, "pre-ollama note", "local-hash-384", 384)
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"

    started: list[int] = []

    def spy(db, cfg=None, **kw):
        started.append(1)
        return 0

    monkeypatch.setattr(mod, "backfill_embeddings", spy)
    import fleeting.main as main_mod

    task = main_mod._maybe_backfill_embeddings(st.db, st.cfg, st.bus)
    assert task is not None, "stale corpus was detected but no migration was scheduled"
    await task
    assert started, "the migration task ran but embedded nothing"


@pytest.mark.anyio
async def test_boot_skips_the_migration_when_the_corpus_is_current(
    client, monkeypatch
) -> None:
    """Boot must stay cheap in the common case: nothing stale, no task."""
    import fleeting.services.embeddings as mod

    st = client.app.state.st
    _note(st.db, "current note", "nomic-embed-text", 768)
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"

    def boom(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("migrated a corpus that was already current")

    monkeypatch.setattr(mod, "backfill_embeddings", boom)
    import fleeting.main as main_mod

    assert main_mod._maybe_backfill_embeddings(st.db, st.cfg, st.bus) is None


def test_boot_skips_the_migration_without_an_llm(client) -> None:
    """No LLM means no migration to run — and no pointless boot cost."""
    st = client.app.state.st
    _note(st.db, "offline note", "local-hash-384", 384)
    st.cfg.llm.provider = "none"
    import fleeting.main as main_mod

    assert main_mod._maybe_backfill_embeddings(st.db, st.cfg, st.bus) is None
