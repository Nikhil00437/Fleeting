"""#321 search feedback (rank demotion) and #322/#49 query log tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import wait_done

from fleeting.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


@pytest.fixture
def two_notes(client: TestClient) -> tuple[str, str]:
    """Two searchable notes; returns (first_id, second_id)."""
    r1 = client.post("/api/capture/text", json={"text": "Router wireless setup guide.", "title": "Router setup"})
    wait_done(client, r1.json()["id"])
    r2 = client.post("/api/capture/text", json={"text": "Router security hardening checklist.", "title": "Router hardening"})
    wait_done(client, r2.json()["id"])
    return r1.json()["id"], r2.json()["id"]


# ---------------------------------------------------------------------------
# query log (#322/#49)
# ---------------------------------------------------------------------------


def test_record_query_canonicalises_and_counts(db: Database) -> None:
    db.record_query("Router  Setup ", 5)
    db.record_query("router setup", 5)
    db.record_query("ROUTER setup", 3)
    log = db.query_log()
    assert len(log) == 1
    assert log[0]["q"] == "router setup"
    assert log[0]["searched"] == 3
    assert log[0]["hits"] == 3  # last result count wins


def test_record_query_ignores_typeahead_debris(db: Database) -> None:
    db.record_query("r", 0)
    db.record_query(" ", 0)
    assert db.query_log() == []


def test_query_log_capped_lru(db: Database) -> None:
    from fleeting.db import QUERY_LOG_CAP

    for i in range(QUERY_LOG_CAP + 10):
        db.record_query(f"query number {i}", 0)
    log = db.query_log(limit=100)
    assert db.execute("SELECT COUNT(*) AS c FROM query_log").fetchone()["c"] == QUERY_LOG_CAP
    # The oldest queries were evicted, the newest survived.
    qs = {row["q"] for row in log}
    assert f"query number {QUERY_LOG_CAP + 9}" in qs
    assert "query number 0" not in qs


def test_query_log_sort_top_vs_recent(db: Database) -> None:
    db.record_query("rare", 1)
    db.record_query("popular", 1)
    db.record_query("popular", 1)
    db.record_query("popular", 1)
    top = db.query_log(limit=5, sort="top")
    assert top[0]["q"] == "popular"
    recent = db.query_log(limit=5, sort="recent")
    assert recent[0]["q"] == "popular"  # last_at tiebreak, ran most recently


def test_api_search_feeds_log_and_history_endpoint(client: TestClient) -> None:
    r = client.post("/api/capture/text", json={"text": "Kubernetes ingress controllers explained.", "title": "K8s ingress"})
    wait_done(client, r.json()["id"])
    client.get("/api/search", params={"q": "Kubernetes ingress"})
    client.get("/api/search", params={"q": "kubernetes INGRESS"})
    client.get("/api/search", params={"q": "kubernetes ingress"})

    history = client.get("/api/search/history").json()
    assert history["recent"][0]["q"] == "kubernetes ingress"
    assert history["recent"][0]["searched"] == 3
    assert history["top"][0]["q"] == "kubernetes ingress"

    # Single-character queries are not logged.
    client.get("/api/search", params={"q": "k"})
    assert all(e["q"] != "k" for e in client.get("/api/search/history").json()["recent"])


# ---------------------------------------------------------------------------
# search feedback / "not relevant" (#321)
# ---------------------------------------------------------------------------


def test_feedback_demotes_note_for_query(client: TestClient, two_notes: tuple[str, str]) -> None:
    first, second = two_notes

    client.post("/api/search/feedback", json={"note_id": first, "query": "router"})
    res = client.get("/api/search", params={"q": "router"}).json()
    assert [n["id"] for n in res] == [second, first]
    assert res[0]["feedback_down"] is False
    assert res[1]["feedback_down"] is True

    # Case/whitespace variants of the query share the same feedback.
    res = client.get("/api/search", params={"q": " ROUTER "}).json()
    assert [n["id"] for n in res] == [second, first]


def test_feedback_undo_restores_rank(client: TestClient, two_notes: tuple[str, str]) -> None:
    first, second = two_notes
    client.post("/api/search/feedback", json={"note_id": first, "query": "router"})
    client.post("/api/search/feedback", json={"note_id": first, "query": "router", "down": False})
    res = client.get("/api/search", params={"q": "router"}).json()
    assert res[0]["id"] == first
    assert res[0]["feedback_down"] is False


def test_feedback_is_query_scoped(client: TestClient, two_notes: tuple[str, str]) -> None:
    first, _ = two_notes
    client.post("/api/search/feedback", json={"note_id": first, "query": "router"})
    res = client.get("/api/search", params={"q": "wireless"}).json()
    assert res[0]["id"] == first


def test_feedback_requires_existing_note(client: TestClient) -> None:
    r = client.post("/api/search/feedback", json={"note_id": "missing", "query": "router"})
    assert r.status_code == 404


def test_feedback_applies_in_keyword_mode(client: TestClient, two_notes: tuple[str, str]) -> None:
    first, second = two_notes
    client.post("/api/search/feedback", json={"note_id": first, "query": "router"})
    res = client.get("/api/search", params={"q": "router", "mode": "keyword"}).json()
    assert [n["id"] for n in res] == [second, first]
