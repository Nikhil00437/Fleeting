"""Degradation must be reported, not just logged.

The app's promise is that it works offline with no API keys, so degrading to
heuristics is *correct*. What is not correct is degrading silently: a failed
embedding call logged at DEBUG, swallowed search errors, and an LLM probe that
just writes a log line all leave the user believing semantic search and
enrichment are running when they are not.

`/api/health` is the one place the UI can learn the truth, so it must answer
"what is degraded and why" — not just "is the DB reachable".
"""

from __future__ import annotations

import sqlite3

import pytest


def _health(client) -> dict:
    r = client.get("/api/health")
    assert r.status_code == 200
    return r.json()


def test_health_reports_degradations_list(client) -> None:
    h = _health(client)
    assert "degradations" in h, "health has no way to tell the UI what is degraded"
    assert isinstance(h["degradations"], list)


def test_health_ok_reflects_no_hard_failures(client) -> None:
    """A heuristic-only setup is degraded but not broken: db works, app runs."""
    h = _health(client)
    assert h["db"] is True
    assert h["ok"] is True


def test_provider_none_is_reported_as_degraded(client) -> None:
    """conftest sets provider='none'; enrichment cannot be running."""
    h = _health(client)
    assert any("llm" in d.lower() or "heuristic" in d.lower() for d in h["degradations"]), (
        f"provider=none not surfaced: {h['degradations']}"
    )


def test_health_reports_embedding_mode(client) -> None:
    h = _health(client)
    assert "embedding_model" in h
    # With provider=none the app is on the offline hash fallback.
    assert h["embedding_model"] == "local-hash-384"
    assert h["semantic_search"] == "lexical" or h["semantic_search"] is False


def test_health_embedding_mode_upgrades_when_llm_reachable(client) -> None:
    """The UI must be able to show that real embeddings are in use."""
    st = client.app.state.st
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"
    h = _health(client)
    assert h["embedding_model"] == "nomic-embed-text"
    assert h["semantic_search"] == "semantic"


def test_health_reports_stale_embedding_count(client, monkeypatch) -> None:
    """Notes embedded by the offline fallback cannot be compared with real ones."""
    from fleeting.db import Database

    db: Database = client.app.state.st.db
    note = db.insert_note({"raw_text": "old note", "type": "text"})
    nid = note["id"] if isinstance(note, dict) else note
    from fleeting.services.embeddings import LocalHashVectorizer, pack_vector

    vec = LocalHashVectorizer().embed("old note")
    db.upsert_note_embedding(nid, pack_vector(vec), len(vec), "local-hash-384")

    st = client.app.state.st
    st.cfg.llm.provider = "ollama"
    st.cfg.llm.model = "nomic-embed-text"

    h = _health(client)
    assert h["stale_embeddings"] == 1
    assert any("stale" in d.lower() or "embedding" in d.lower() for d in h["degradations"])


def test_health_reports_zero_stale_when_all_current(client) -> None:
    h = _health(client)
    assert h["stale_embeddings"] == 0


def test_health_survives_a_dead_database(client, monkeypatch) -> None:
    """A failing DB probe must not 500 the one endpoint the UI polls."""

    def boom(*a, **kw):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(client.app.state.st.db, "count_notes", boom)
    h = _health(client)
    assert h["db"] is False
    assert h["ok"] is False
    assert any("database" in d.lower() for d in h["degradations"])


def test_health_degradation_messages_are_actionable(client) -> None:
    """No bare 'error' — the message should say what is wrong."""
    for d in _health(client)["degradations"]:
        assert len(d) > 15, f"not actionable: {d!r}"
        assert d[0].isupper(), f"not a sentence: {d!r}"


def test_health_never_leaks_the_api_key(client) -> None:
    st = client.app.state.st
    st.cfg.llm.api_key = "sk-super-secret-value"
    body = str(_health(client))
    assert "sk-super-secret" not in body


def test_health_still_reports_queue_depth(client) -> None:
    """Existing fields must not regress."""
    h = _health(client)
    assert "queue" in h
    assert "uptime_secs" in h
    assert "whisper_loaded" in h
    assert "version" in h