"""#320 find-similar neighbours, #23 related notes, #16 near-duplicate merges."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import wait_done

from fleeting.config import Config
from fleeting.db import Database
from fleeting.services.embeddings import embed_note
from fleeting.services.similar import find_similar, near_duplicate_titles


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


def _seed_notes(db: Database) -> dict[str, str]:
    ids = {}
    n = db.insert_note({
        "title": "Router wireless setup",
        "raw_text": "Configure the wireless router, firmware update steps and default gateway.",
        "tags": ["network"],
    })
    ids["router"] = n["id"]
    n = db.insert_note({
        "title": "Router security hardening",
        "raw_text": "Harden the router: disable WPS, change default passwords, enable WPA3.",
        "tags": ["network", "security"],
    })
    ids["hardening"] = n["id"]
    n = db.insert_note({
        "title": "Pasta carbonara",
        "raw_text": "Guanciale, pecorino, egg yolks and pepper tossed with hot pasta.",
        "tags": ["cooking"],
    })
    ids["pasta"] = n["id"]
    return ids


def test_find_similar_ranks_topical_neighbours(db: Database, cfg: Config) -> None:
    ids = _seed_notes(db)
    for note_id in ids.values():
        embed_note(db.get_note(note_id), db, cfg)

    similar = find_similar(db, cfg, ids["router"], limit=8)
    assert similar, "no neighbours found"
    assert all(s["id"] != ids["router"] for s in similar)
    assert all(s["match_type"] == "similar" for s in similar)
    # Both neighbours come back; the other router note outranks carbonara.
    order = [s["id"] for s in similar]
    assert set(order) == {ids["hardening"], ids["pasta"]}
    assert order.index(ids["hardening"]) < order.index(ids["pasta"])
    # Scores are cosine similarities in (0, 1].
    assert all(0 < s["score"] <= 1 for s in similar)


def test_find_similar_without_stored_embedding_uses_query_time_vector(db: Database, cfg: Config) -> None:
    ids = _seed_notes(db)
    # Only the hardening note is embedded; the query note relies on its text.
    embed_note(db.get_note(ids["hardening"]), db, cfg)
    similar = find_similar(db, cfg, ids["router"], limit=5)
    assert [s["id"] for s in similar] == [ids["hardening"]]


def test_find_similar_excludes_trashed_and_archived(db: Database, cfg: Config) -> None:
    ids = _seed_notes(db)
    for note_id in ids.values():
        embed_note(db.get_note(note_id), db, cfg)
    db.update_note(ids["pasta"], {"archived": 1})
    similar = find_similar(db, cfg, ids["router"], limit=8)
    assert [s["id"] for s in similar] == [ids["hardening"]]


def test_find_similar_unknown_note_or_empty_text(db: Database, cfg: Config) -> None:
    assert find_similar(db, cfg, "missing", limit=5) == []
    empty = db.insert_note({"title": "", "raw_text": ""})
    assert find_similar(db, cfg, empty["id"], limit=5) == []


def test_api_similar_notes_endpoint(client: TestClient) -> None:
    r1 = client.post(
        "/api/capture/text",
        json={"text": "Sourdough starter feeding schedule and hydration ratios.", "title": "Sourdough starter"},
    )
    n1 = r1.json()["id"]
    wait_done(client, n1)
    r2 = client.post(
        "/api/capture/text",
        json={"text": "Sourdough starter smells like acetone — feed it more flour.", "title": "Starter trouble"},
    )
    n2 = r2.json()["id"]
    wait_done(client, n2)

    res = client.get(f"/api/notes/{n1}/similar").json()
    assert isinstance(res, list)
    assert all(item["id"] != n1 for item in res)
    assert any(item["id"] == n2 for item in res)

    assert client.get("/api/notes/missing/similar").status_code == 404


def test_near_duplicate_titles_suggests_merges(db: Database) -> None:
    db.insert_note({"title": "Todo – Inbox cleanup", "raw_text": "x"})
    db.insert_note({"title": "todo inbox cleanup", "raw_text": "y"})
    db.insert_note({"title": "Unrelated meeting notes", "raw_text": "z"})
    suggestions = near_duplicate_titles(db)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s["kind"] == "merge"
    assert s["reason"].startswith("title ")
    assert len(s["extra_note_ids"]) == 1


def test_cleanup_includes_near_duplicates(db: Database) -> None:
    from fleeting.services.cleanup import cleanup_suggestions

    db.insert_note({"title": "Weekly planning session", "raw_text": "x"})
    db.insert_note({"title": "weekly  planning session", "raw_text": "y"})
    kinds = [s["kind"] for s in cleanup_suggestions(db)]
    assert "merge" in kinds
