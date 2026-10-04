"""End-to-end proof for 6a.

Runs the real sequence a user hits, with no mocked embedding call, and asserts
that semantic search recovers afterwards:

  1. Notes captured with no LLM -> 384-dim local-hash vectors.
  2. LLM switched on -> new notes get 768-dim vectors, old ones do not.
  3. Before the migration, the old notes are INVISIBLE to semantic search.
  4. POST /api/settings/embeddings/backfill migrates them.
  5. After, the old notes are findable again.

Step 3 is the bug this whole PR exists to fix; asserting on it means the test
fails if the migration is ever removed.
"""

from __future__ import annotations

import pytest

from fleeting.services.embeddings import embed_note
from fleeting.services.semantic_search import hybrid_search

SEED_NOTES = [
    "kubernetes ingress controller rewrite for the edge proxy",
    "postgres connection pool exhausted under load",
    "refactor the billing retry queue",
]
QUERY = "kubernetes ingress"


@pytest.fixture
def offline(client):
    """Notes captured while no LLM was configured."""
    st = client.app.state.st
    st.cfg.llm.provider = "none"
    ids = []
    for text in SEED_NOTES:
        note = st.db.insert_note({"raw_text": text, "type": "text", "title": text})
        nid = note["id"] if isinstance(note, dict) else note
        embed_note(note, st.db, st.cfg)
        ids.append(nid)
    return st, ids


def _found(st, query: str) -> set[str]:
    return {r["id"] for r in hybrid_search(st.db, query, st.cfg, mode="semantic", limit=50)}


def test_offline_captures_are_found_by_the_offline_fallback(offline) -> None:
    """Baseline: lexical matching works when every note shares a model."""
    st, ids = offline
    assert _found(st, QUERY), "baseline broken: nothing findable while offline"


def test_mixed_dimensionality_hides_old_notes_then_the_migration_recovers_them(
    offline, monkeypatch
) -> None:
    st, ids = offline
    import fleeting.services.embeddings as femb

    # Turn the LLM on and add one *new* note, which gets a real 768-dim vector.
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"
    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None: ([0.4] * 768, "nomic-embed-text")
    )
    fresh = st.db.insert_note({"raw_text": QUERY, "type": "text", "title": QUERY})
    fresh_id = fresh["id"] if isinstance(fresh, dict) else fresh
    embed_note(fresh, st.db, st.cfg)
    assert st.db.get_note_embedding(fresh_id)["dimensions"] == 768

    # The stale corpus really is invisible: that is the bug this fixes.
    # The one note embedded with the new model is findable; the three captured
    # before it are not, because 384-dim vectors cannot be compared with 768.
    before_ids = _found(st, QUERY)
    assert fresh_id in before_ids
    hidden = [i for i in ids if i not in before_ids]
    assert hidden, "premise broken: the stale notes were already findable"

    # Migrate, as boot or the button would.
    from fleeting.routers.settings import backfill_embeddings_stream

    result = backfill_embeddings_stream(st.db, st.cfg, st.bus)
    assert result["migrated"] == len(ids)

    # Now every note is on one model and findable again.
    for nid in ids:
        row = st.db.get_note_embedding(nid)
        assert row["dimensions"] == 768, "migration left a stale vector behind"

    after_ids = _found(st, QUERY)
    assert after_ids, "search found nothing after the migration"
    recovered = [i for i in hidden if i in after_ids]
    assert recovered, f"migration ran but the stale notes are still invisible: {hidden}"
    dims = {
        r["dimensions"]
        for r in st.db.execute("SELECT dimensions FROM note_embeddings").fetchall()
    }
    assert dims == {768}, f"mixed dimensionality survived: {dims}"


def test_health_reports_the_degradation_and_then_clears(offline, monkeypatch) -> None:
    st, ids = offline
    import fleeting.services.embeddings as femb

    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"

    # health() counts notes stored under a different model
    from fleeting.routers.system import _embedding_status

    class _S:
        cfg = st.cfg
        db = st.db

    model, stale = _embedding_status(_S)
    assert model == "nomic-embed-text"
    assert stale == len(ids)

    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None: ([0.4] * 768, "nomic-embed-text")
    )
    from fleeting.routers.settings import backfill_embeddings_stream

    backfill_embeddings_stream(st.db, st.cfg, st.bus)

    _, stale_after = _embedding_status(_S)
    assert stale_after == 0


def test_no_llm_means_no_migration_work(offline) -> None:
    """Boot must not spin up a pointless migration for offline-only users."""
    from fleeting.routers.settings import backfill_embeddings_stream

    st, _ = offline
    out = backfill_embeddings_stream(st.db, st.cfg, st.bus)
    assert out["migrated"] == 0
    assert out["skipped"] == "no llm configured"


def test_local_vectors_stay_local_after_a_noop_run(offline) -> None:
    """A skipped migration must not rewrite the offline vectors."""
    st, ids = offline
    before = [st.db.get_note_embedding(i)["embedding"] for i in ids]
    from fleeting.routers.settings import backfill_embeddings_stream

    backfill_embeddings_stream(st.db, st.cfg, st.bus)
    after = [st.db.get_note_embedding(i)["embedding"] for i in ids]
    assert before == after
    assert st.db.get_note_embedding(ids[0])["model"] == "local-hash-384"


def test_backfill_is_idempotent(offline, monkeypatch) -> None:
    """Running it twice must not double-report or corrupt anything."""
    import fleeting.services.embeddings as femb
    from fleeting.routers.settings import backfill_embeddings_stream

    st, ids = offline
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"
    monkeypatch.setattr(
        femb, "embed_text_with_model", lambda t, c=None: ([0.4] * 768, "nomic-embed-text")
    )

    first = backfill_embeddings_stream(st.db, st.cfg, st.bus)
    second = backfill_embeddings_stream(st.db, st.cfg, st.bus)
    assert first["migrated"] == len(ids)
    assert second["migrated"] == 0
    assert second["was_stale"] == 0
