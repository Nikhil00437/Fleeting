"""Unit and integration tests for hybrid search, semantic recall, and automatic note embeddings."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import wait_done

from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.embeddings import embed_note, unpack_vector
from fleeting.services.semantic_search import hybrid_search
from fleeting.services.vault_watcher import sync_file_change


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    c = Config()
    c.llm.provider = "none"
    c.paths.vault_dir = str(tmp_path / "vault")
    return c


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ---------------------------------------------------------------------------
# 1. Empty / Whitespace Query
# ---------------------------------------------------------------------------


def test_empty_or_whitespace_query(db: Database, cfg: Config) -> None:
    db.insert_note({"title": "Sample Note", "raw_text": "Content here."})
    assert hybrid_search(db, "", cfg) == []
    assert hybrid_search(db, "   ", cfg) == []
    assert hybrid_search(db, "\t\n", cfg) == []


# ---------------------------------------------------------------------------
# 2. Keyword Mode
# ---------------------------------------------------------------------------


def test_keyword_mode(db: Database, cfg: Config) -> None:
    note1 = db.insert_note({
        "title": "Quantum Computing",
        "raw_text": "Quantum algorithms run on qubits and use superposition.",
    })
    note2 = db.insert_note({
        "title": "Cooking Pasta",
        "raw_text": "Boil water with salt, add pasta for 10 minutes.",
    })

    results = hybrid_search(db, "superposition", cfg, mode="keyword")
    assert len(results) == 1
    assert results[0]["id"] == note1["id"]
    assert results[0]["match_type"] == "keyword"
    assert isinstance(results[0]["score"], float)
    assert results[0]["score"] > 0.0
    assert "superposition" in results[0]["snippet"].lower()


# ---------------------------------------------------------------------------
# 3. Semantic Mode & Conceptual Matches
# ---------------------------------------------------------------------------


def test_semantic_mode_finds_conceptual_match_without_exact_fts(db: Database, cfg: Config) -> None:
    # FTS prefix query for "architectural" will NOT match exact token "architecture"
    note = db.insert_note({
        "title": "Scalable Microservices",
        "raw_text": "Building scalable architecture with microservices.",
    })
    embed_note(note, db, cfg)

    # Confirm FTS5 does not match
    fts_results = db.search("architectural")
    assert len(fts_results) == 0

    # Semantic search matches via character 3-gram subwords in LocalHashVectorizer
    sem_results = hybrid_search(db, "architectural", cfg, mode="semantic")
    assert len(sem_results) == 1
    assert sem_results[0]["id"] == note["id"]
    assert sem_results[0]["match_type"] == "semantic"
    assert sem_results[0]["score"] > 0.0
    assert sem_results[0]["snippet"] != ""


def test_semantic_mode_discards_irrelevant(db: Database, cfg: Config) -> None:
    note = db.insert_note({
        "title": "Quantum Physics",
        "raw_text": "Subatomic particle interactions and wave function collapse.",
    })
    embed_note(note, db, cfg)

    # Completely unrelated query
    results = hybrid_search(db, "baking chocolate chip cookies recipe", cfg, mode="semantic")
    # Low cosine similarity (<= 0.05) is discarded
    assert len(results) == 0


# ---------------------------------------------------------------------------
# 4. Hybrid Mode Prioritizing Both Matches (RRF)
# ---------------------------------------------------------------------------


def test_hybrid_mode_prioritizes_both(db: Database, cfg: Config) -> None:
    # Note 1: Matched by both FTS5 keyword AND vector similarity
    note1 = db.insert_note({
        "title": "Rust Compiler Safety",
        "raw_text": "Rust borrow checker ensures memory safety without a garbage collector.",
        "summary": "Rust memory safety compiler borrow checker.",
    })
    embed_note(note1, db, cfg)

    # Note 2: Keyword match for "Rust" only, but text is largely about unrelated grocery items
    note2 = db.insert_note({
        "title": "Shopping List with Rust Book",
        "raw_text": "Buy apples, bananas, milk, eggs, carrots, spinach, bread, and read Rust book.",
        "summary": "Grocery shopping list with a quick mention of Rust book.",
    })
    embed_note(note2, db, cfg)

    # Note 3: Semantic match for borrow checker concept without exact keyword "Rust"
    note3 = db.insert_note({
        "title": "Memory Safety Mechanisms",
        "raw_text": "Borrow checker guarantees memory safety and prevents data races.",
        "summary": "Memory safety without garbage collection using compile-time checks.",
    })
    embed_note(note3, db, cfg)

    results = hybrid_search(db, "Rust borrow checker compiler", cfg, mode="hybrid")
    assert len(results) >= 2
    # Note 1 should be #1 because it has both strong keyword and strong semantic rank
    assert results[0]["id"] == note1["id"]
    assert results[0]["match_type"] == "hybrid"
    assert results[0]["score"] == 1.0  # normalized top score is 1.0

    # Note 2 or Note 3 will have lower score (< 1.0)
    for lower_result in results[1:]:
        assert lower_result["score"] < 1.0


# ---------------------------------------------------------------------------
# 5. Facet Filtering by Note Type and Repository
# ---------------------------------------------------------------------------


def test_filtering_by_type(db: Database, cfg: Config) -> None:
    text_note = db.insert_note({
        "type": "text",
        "title": "Weekly Planning Meeting",
        "raw_text": "Discuss roadmap milestones and sprint deliverables.",
    })
    voice_note = db.insert_note({
        "type": "voice",
        "title": "Voice Memo Planning",
        "raw_text": "Audio transcription: Discuss roadmap milestones and sprint deliverables.",
    })

    text_results = hybrid_search(db, "roadmap milestones", cfg, filter_type="text")
    assert len(text_results) == 1
    assert text_results[0]["id"] == text_note["id"]

    voice_results = hybrid_search(db, "roadmap milestones", cfg, filter_type="voice")
    assert len(voice_results) == 1
    assert voice_results[0]["id"] == voice_note["id"]


def test_filtering_by_repo(db: Database, cfg: Config) -> None:
    # Note 1: Match repo via task
    note1 = db.insert_note({
        "title": "Backend Optimization",
        "raw_text": "Refactor database connection pool.",
    })
    db.insert_task({
        "note_id": note1["id"],
        "text": "Optimize connection pool",
        "repo": "fleeting-core",
    })

    # Note 2: Match repo via source dict
    note2 = db.insert_note({
        "title": "UI Component Refresh",
        "raw_text": "Redesign button and card components.",
        "source": {"repo": "fleeting-ui"},
    })

    # Note 3: Match repo via tag with leading '#'
    note3 = db.insert_note({
        "title": "Documentation Update",
        "raw_text": "Update architecture overview and deployment guide.",
        "tags": ["#fleeting-docs"],
    })

    # Note 4: No repo
    note4 = db.insert_note({
        "title": "Random Thoughts",
        "raw_text": "Ideas for future blog posts.",
    })

    # Filter by task repo
    res1 = hybrid_search(db, "Refactor database", cfg, repo="fleeting-core")
    assert len(res1) == 1
    assert res1[0]["id"] == note1["id"]

    # Filter by source repo (case-insensitive)
    res2 = hybrid_search(db, "Redesign button", cfg, repo="FLEETING-UI")
    assert len(res2) == 1
    assert res2[0]["id"] == note2["id"]

    # Filter by tag repo (stripping leading '#')
    res3 = hybrid_search(db, "architecture overview", cfg, repo="fleeting-docs")
    assert len(res3) == 1
    assert res3[0]["id"] == note3["id"]

    # Filter by non-existent repo
    res_none = hybrid_search(db, "Refactor database", cfg, repo="nonexistent-repo")
    assert len(res_none) == 0


# ---------------------------------------------------------------------------
# 6. Exclude Archived Notes
# ---------------------------------------------------------------------------


def test_archived_notes_excluded(db: Database, cfg: Config) -> None:
    active_note = db.insert_note({
        "title": "Active Architecture Note",
        "raw_text": "Microservices event-driven streaming architecture.",
        "archived": False,
    })
    embed_note(active_note, db, cfg)

    archived_note = db.insert_note({
        "title": "Old Archived Architecture Note",
        "raw_text": "Microservices event-driven streaming architecture deprecated.",
        "archived": True,
    })
    embed_note(archived_note, db, cfg)

    # Keyword mode
    kw_res = hybrid_search(db, "streaming architecture", cfg, mode="keyword")
    assert all(r["id"] != archived_note["id"] for r in kw_res)
    assert any(r["id"] == active_note["id"] for r in kw_res)

    # Semantic mode
    sem_res = hybrid_search(db, "streaming architecture", cfg, mode="semantic")
    assert all(r["id"] != archived_note["id"] for r in sem_res)
    assert any(r["id"] == active_note["id"] for r in sem_res)

    # Hybrid mode
    hyb_res = hybrid_search(db, "streaming architecture", cfg, mode="hybrid")
    assert all(r["id"] != archived_note["id"] for r in hyb_res)
    assert any(r["id"] == active_note["id"] for r in hyb_res)


# ---------------------------------------------------------------------------
# 7. Search API Router Endpoints
# ---------------------------------------------------------------------------


def test_api_search_endpoint_with_query_params(client: TestClient) -> None:
    # Create notes via capture endpoint
    r1 = client.post("/api/capture/text", json={"text": "Rust concurrency async await tokio", "title": "Rust Async"})
    n1_id = r1.json()["id"]
    wait_done(client, n1_id)

    r2 = client.post("/api/capture/text", json={"text": "Python fastapi web framework", "title": "Python FastAPI"})
    n2_id = r2.json()["id"]
    wait_done(client, n2_id)

    # Search with hybrid mode (default)
    res_default = client.get("/api/search", params={"q": "async await"}).json()
    assert len(res_default) >= 1
    assert res_default[0]["id"] == n1_id
    assert res_default[0]["score"] is not None
    assert res_default[0]["match_type"] in ("hybrid", "keyword", "semantic")

    # Search with explicit mode=keyword
    res_kw = client.get("/api/search", params={"q": "fastapi", "mode": "keyword"}).json()
    assert len(res_kw) >= 1
    assert res_kw[0]["id"] == n2_id
    assert res_kw[0]["match_type"] == "keyword"

    # Search with explicit mode=semantic
    res_sem = client.get("/api/search", params={"q": "tokio runtime", "mode": "semantic"}).json()
    assert len(res_sem) >= 1
    assert res_sem[0]["id"] == n1_id
    assert res_sem[0]["match_type"] == "semantic"

    # Search with type filter
    res_type = client.get("/api/search", params={"q": "async", "type": "voice"}).json()
    assert len(res_type) == 0

    # Search with empty query returns empty list
    res_empty = client.get("/api/search", params={"q": "   "}).json()
    assert res_empty == []


# ---------------------------------------------------------------------------
# 7b. Operator syntax through the API (#313/#315/#318)
# ---------------------------------------------------------------------------


def test_api_search_operator_syntax_and_alpha(client: TestClient) -> None:
    r1 = client.post(
        "/api/capture/text",
        json={"text": "Router wireless setup guide with firmware notes.", "title": "Router setup", "tags": ["infra"]},
    )
    n1 = r1.json()["id"]
    wait_done(client, n1)
    r2 = client.post(
        "/api/capture/text",
        json={"text": "Draft plan for the office router replacement.", "title": "Office router draft"},
    )
    n2 = r2.json()["id"]
    wait_done(client, n2)

    # The heuristic pipeline derives its own tags on capture, so the tag
    # under test is applied after processing.
    client.patch(f"/api/notes/{n1}", json={"tags": ["infra"]})

    # Exclusion operator.
    res = client.get("/api/search", params={"q": "router -draft"}).json()
    assert [n["id"] for n in res] == [n1]

    # Tag operator.
    res = client.get("/api/search", params={"q": "tag:infra"}).json()
    assert [n["id"] for n in res] == [n1]

    # Type operator.
    res = client.get("/api/search", params={"q": "router type:text"}).json()
    assert {n["id"] for n in res} == {n1, n2}

    # Exact phrase.
    res = client.get("/api/search", params={"q": '"wireless setup"'}).json()
    assert [n["id"] for n in res] == [n1]

    # Filters alone (no text units) still return the tagged note.
    res = client.get("/api/search", params={"q": "tag:infra type:text"}).json()
    assert [n["id"] for n in res] == [n1]

    # #315: alpha is accepted and clamped server-side; results stay valid.
    for alpha in ("0.0", "1.0", "0.25"):
        res = client.get("/api/search", params={"q": "router", "alpha": alpha}).json()
        assert n1 in {n["id"] for n in res}

    # Out-of-range alpha is rejected by validation.
    assert client.get("/api/search", params={"q": "router", "alpha": "2.0"}).status_code == 422


# ---------------------------------------------------------------------------
# 8. Automatic Embedding Hooks (Processor & Vault Watcher)
# ---------------------------------------------------------------------------


def test_processor_populates_embeddings(client: TestClient) -> None:
    db = client.app.state.st.db
    r = client.post(
        "/api/capture/text",
        json={"text": "Distributed systems and consensus protocols with Raft.", "title": "Raft Consensus"},
    )
    note_id = r.json()["id"]
    wait_done(client, note_id)

    embedding_record = db.get_note_embedding(note_id)
    assert embedding_record is not None
    assert embedding_record["dimensions"] == 384
    assert len(embedding_record["embedding"]) == 384 * 4
    unpacked = unpack_vector(embedding_record["embedding"])
    assert len(unpacked) == 384


def test_vault_watcher_sync_populates_embeddings(tmp_path: Path, db: Database, bus: EventBus, cfg: Config) -> None:
    vault_dir = Path(cfg.paths.vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    # 1. Test creation of new note in vault
    md_file = vault_dir / "fleeting-test-new-note.md"
    md_file.write_text(
        "---\ntype: text\ntitle: Distributed Tracing\ntags:\n  - observability\n---\n"
        "OpenTelemetry and Jaeger for distributed tracing in cloud microservices.\n",
        encoding="utf-8",
    )

    res = sync_file_change(md_file, db, bus, cfg)
    assert res is not None
    assert res["action"] == "created"
    note_id = res["note_id"]

    emb = db.get_note_embedding(note_id)
    assert emb is not None
    assert emb["dimensions"] == 384

    # 2. Test update of existing note in vault
    updated_content = (
        f"---\nid: {note_id}\ntype: text\ntitle: Distributed Tracing Updated\ntags:\n  - observability\n---\n"
        "OpenTelemetry metrics and traces with Prometheus and Grafana dashboards.\n"
    )
    md_file.write_text(updated_content, encoding="utf-8")

    res_upd = sync_file_change(md_file, db, bus, cfg)
    assert res_upd is not None
    assert res_upd["action"] == "updated"

    emb_upd = db.get_note_embedding(note_id)
    assert emb_upd is not None
    assert emb_upd["updated_at"] is not None
