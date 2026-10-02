"""Unit tests for vector storage, serialization, LocalHashVectorizer, and embedding service."""

from __future__ import annotations

import math
import struct
from unittest.mock import MagicMock, patch

import pytest
import httpx

from fleeting.config import Config, LLMConfig
from fleeting.db import Database
from fleeting.services.embeddings import (
    LocalHashVectorizer,
    backfill_embeddings,
    cosine_similarity,
    embed_note,
    embed_text,
    embed_text_with_model,
    pack_vector,
    unpack_vector,
)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def cfg():
    c = Config()
    c.llm.provider = "none"
    return c


# ---------------------------------------------------------------------------
# Vector packing & unpacking
# ---------------------------------------------------------------------------


def test_pack_and_unpack_vector_roundtrip_exact():
    vec = [0.0, 1.0, -1.0, 0.5, -0.25, 0.125]
    packed = pack_vector(vec)
    assert isinstance(packed, bytes)
    assert len(packed) == len(vec) * 4
    unpacked = unpack_vector(packed)
    assert unpacked == vec


def test_pack_and_unpack_vector_precision():
    vec = [0.1234567, -0.9876543, 0.5555555]
    packed = pack_vector(vec)
    unpacked = unpack_vector(packed)
    assert len(unpacked) == len(vec)
    for original, recovered in zip(vec, unpacked):
        assert math.isclose(original, recovered, rel_tol=1e-6, abs_tol=1e-6)


def test_pack_and_unpack_384_dimensions():
    vec = [float(i) / 384.0 for i in range(384)]
    packed = pack_vector(vec)
    assert len(packed) == 384 * 4
    unpacked = unpack_vector(packed)
    assert len(unpacked) == 384
    # Round-trip of the unpacked vector must be bitwise identical
    assert unpack_vector(pack_vector(unpacked)) == unpacked


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors():
    u = [0.6, 0.8, 0.0]
    sim = cosine_similarity(u, u)
    assert math.isclose(sim, 1.0, abs_tol=1e-6)


def test_cosine_similarity_unnormalized_identical_vectors():
    u = [3.0, 4.0, 0.0]
    sim = cosine_similarity(u, u)
    assert math.isclose(sim, 1.0, abs_tol=1e-6)


def test_cosine_similarity_orthogonal_vectors():
    u = [1.0, 0.0, 0.0]
    v = [0.0, 1.0, 0.0]
    sim = cosine_similarity(u, v)
    assert math.isclose(sim, 0.0, abs_tol=1e-6)


def test_cosine_similarity_opposite_vectors():
    u = [0.5, 0.5, 0.5, 0.5]
    v = [-0.5, -0.5, -0.5, -0.5]
    sim = cosine_similarity(u, v)
    assert math.isclose(sim, -1.0, abs_tol=1e-6)


def test_cosine_similarity_zero_vectors():
    u = [0.0, 0.0, 0.0]
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(u, v) == 0.0
    assert cosine_similarity(u, u) == 0.0


def test_cosine_similarity_length_mismatch():
    u = [1.0, 0.0]
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(u, v) == 0.0
    assert cosine_similarity([], []) == 0.0


# ---------------------------------------------------------------------------
# LocalHashVectorizer
# ---------------------------------------------------------------------------


def test_local_hash_vectorizer_determinism():
    vectorizer = LocalHashVectorizer(dimensions=384)
    text = "FastAPI authentication service with JWT token verification"
    v1 = vectorizer.embed(text)
    v2 = vectorizer.embed(text)
    assert len(v1) == 384
    assert v1 == v2


def test_local_hash_vectorizer_unit_norm():
    vectorizer = LocalHashVectorizer(dimensions=384)
    v = vectorizer.embed("Some note about SQLite database performance and indexing")
    norm = math.sqrt(sum(x * x for x in v))
    assert math.isclose(norm, 1.0, abs_tol=1e-5)


def test_local_hash_vectorizer_similarity_topical_vs_unrelated():
    vectorizer = LocalHashVectorizer(dimensions=384)
    t1 = "FastAPI authentication with JWT tokens in Python backend"
    t2 = "User authentication and JWT token verification in FastAPI Python"
    t3 = "Recipe for chocolate chip cookies with sea salt and brown butter"

    v1 = vectorizer.embed(t1)
    v2 = vectorizer.embed(t2)
    v3 = vectorizer.embed(t3)

    sim_similar = cosine_similarity(v1, v2)
    sim_unrelated = cosine_similarity(v1, v3)

    # Similar/overlapping text must yield high similarity (> 0.5)
    assert sim_similar > 0.5, f"Expected > 0.5, got {sim_similar}"
    # Unrelated text must yield much lower similarity
    assert sim_unrelated < 0.35, f"Expected < 0.35, got {sim_unrelated}"
    assert sim_similar > sim_unrelated + 0.3


def test_local_hash_vectorizer_empty_and_whitespace():
    vectorizer = LocalHashVectorizer(dimensions=384)
    assert vectorizer.embed("") == [0.0] * 384
    assert vectorizer.embed("   \n\t  ") == [0.0] * 384
    assert vectorizer.embed("!!! ??? ...") == [0.0] * 384


# ---------------------------------------------------------------------------
# Database schema & embedding methods
# ---------------------------------------------------------------------------


def test_schema_migration_v6_note_embeddings_table(db):
    conn = db.conn
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    assert "note_embeddings" in tables

    cols = {r["name"]: r["type"].upper() for r in conn.execute("PRAGMA table_info(note_embeddings)").fetchall()}
    assert "note_id" in cols
    assert "embedding" in cols
    assert "dimensions" in cols
    assert "model" in cols
    assert "updated_at" in cols


def test_db_upsert_and_get_note_embedding(db):
    note = db.insert_note({"title": "Test Note", "raw_text": "Content for testing"})
    vec = [0.1] * 384
    packed = pack_vector(vec)

    db.upsert_note_embedding(note["id"], packed, 384, "local-hash-384")

    stored = db.get_note_embedding(note["id"])
    assert stored is not None
    assert stored["note_id"] == note["id"]
    assert isinstance(stored["embedding"], bytes)
    assert stored["embedding"] == packed
    assert stored["dimensions"] == 384
    assert stored["model"] == "local-hash-384"
    assert "T" in stored["updated_at"]

    # Test unpack matches
    recovered_vec = unpack_vector(stored["embedding"])
    for a, b in zip(vec, recovered_vec):
        assert math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)


def test_db_upsert_replaces_existing(db):
    note = db.insert_note({"title": "Test Note", "raw_text": "Content"})
    vec1 = [0.1] * 384
    vec2 = [0.2] * 384

    db.upsert_note_embedding(note["id"], pack_vector(vec1), 384, "model-1")
    db.upsert_note_embedding(note["id"], pack_vector(vec2), 384, "model-2")

    stored = db.get_note_embedding(note["id"])
    assert stored is not None
    assert stored["model"] == "model-2"
    assert unpack_vector(stored["embedding"])[0] == pytest.approx(0.2, abs=1e-5)


def test_db_get_all_embeddings(db):
    n1 = db.insert_note({"title": "N1", "raw_text": "Text 1"})
    n2 = db.insert_note({"title": "N2", "raw_text": "Text 2"})

    db.upsert_note_embedding(n1["id"], pack_vector([0.1] * 384), 384, "local-hash-384")
    db.upsert_note_embedding(n2["id"], pack_vector([0.2] * 384), 384, "local-hash-384")

    all_embs = db.get_all_embeddings()
    assert len(all_embs) >= 2
    ids = {e["note_id"] for e in all_embs}
    assert n1["id"] in ids
    assert n2["id"] in ids


def test_db_delete_note_embedding(db):
    note = db.insert_note({"title": "Delete Embedding Note", "raw_text": "Content"})
    db.upsert_note_embedding(note["id"], pack_vector([0.1] * 384), 384, "local-hash-384")
    assert db.get_note_embedding(note["id"]) is not None

    db.delete_note_embedding(note["id"])
    assert db.get_note_embedding(note["id"]) is None


def test_foreign_key_cascade_deletes_embedding(db):
    note = db.insert_note({"title": "Cascade Note", "raw_text": "Content to cascade delete"})
    db.upsert_note_embedding(note["id"], pack_vector([0.5] * 384), 384, "local-hash-384")
    assert db.get_note_embedding(note["id"]) is not None

    # Deleting the parent note from notes table must cascade and delete from note_embeddings
    db.delete_note(note["id"])
    assert db.get_note(note["id"]) is None
    assert db.get_note_embedding(note["id"]) is None


# ---------------------------------------------------------------------------
# embed_note, embed_text, and backfill_embeddings
# ---------------------------------------------------------------------------


def test_embed_note_success(db, cfg):
    note = db.insert_note({
        "title": "OAuth Setup",
        "tags": ["auth", "security"],
        "summary": "Setting up Google OAuth 2.0 flow",
        "raw_text": "Full explanation of authorization code exchange.",
    })
    vec = embed_note(note, db, cfg)
    assert vec is not None
    assert len(vec) == 384

    stored = db.get_note_embedding(note["id"])
    assert stored is not None
    assert stored["dimensions"] == 384
    assert stored["model"] == "local-hash-384"
    recovered = unpack_vector(stored["embedding"])
    assert len(recovered) == 384
    assert cosine_similarity(vec, recovered) == pytest.approx(1.0, abs=1e-5)


def test_embed_note_empty_returns_none(db, cfg):
    note = db.insert_note({"title": "", "summary": "", "raw_text": "", "tags": []})
    vec = embed_note(note, db, cfg)
    assert vec is None
    assert db.get_note_embedding(note["id"]) is None


def test_backfill_embeddings(db, cfg):
    # n1: has text, un-embedded
    n1 = db.insert_note({"title": "Note 1", "raw_text": "Important details about Redis cache", "status": "done"})
    # n2: has text, pre-embedded
    n2 = db.insert_note({"title": "Note 2", "raw_text": "PostgreSQL indexing guide", "status": "done"})
    embed_note(n2, db, cfg)
    # n3: archived note, should be skipped
    n3 = db.insert_note({"title": "Note 3", "raw_text": "Old archived note", "status": "done", "archived": 1})

    assert db.get_note_embedding(n1["id"]) is None
    assert db.get_note_embedding(n2["id"]) is not None

    count = backfill_embeddings(db, cfg)
    # Only n1 needed backfill
    assert count == 1
    assert db.get_note_embedding(n1["id"]) is not None
    assert db.get_note_embedding(n3["id"]) is None


def test_embed_text_remote_fallback_on_unreachable_server():
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://127.0.0.1:99999"  # invalid port, won't connect
    cfg.llm.timeout_secs = 1

    vec = embed_text("Hello semantic recall world", cfg)
    assert len(vec) == 384
    # Must match LocalHashVectorizer output
    expected = LocalHashVectorizer().embed("Hello semantic recall world")
    assert vec == expected


def test_embed_text_remote_success_ollama():
    cfg = Config()
    cfg.llm.provider = "ollama"
    cfg.llm.base_url = "http://mock-ollama:11434"
    cfg.llm.model = "nomic-embed-text"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"embedding": [0.6, 0.8] + [0.0] * 382}

    with patch("httpx.Client.post", return_value=mock_resp):
        vec, model = embed_text_with_model("Sample query", cfg)
        assert model == "nomic-embed-text"
        assert len(vec) == 384
        norm = math.sqrt(sum(x * x for x in vec))
        assert math.isclose(norm, 1.0, abs_tol=1e-5)
