"""#50 tag manager (rename/merge/delete) and #425 tag audit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fleeting.db import Database
from fleeting.services.tag_audit import tag_audit


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _tag(db: Database, note_id: str) -> list[str]:
    return db.get_note(note_id)["tags"]


# ---------------------------------------------------------------------------
# db-level rewrite
# ---------------------------------------------------------------------------


def test_rename_tag_rewrites_matching_notes(db: Database) -> None:
    a = db.insert_note({"title": "A", "raw_text": "x", "tags": ["work", "urgent"]})
    b = db.insert_note({"title": "B", "raw_text": "y", "tags": ["#work"]})
    c = db.insert_note({"title": "C", "raw_text": "z", "tags": ["home"]})

    updated = db.rename_tag("work", "job")
    assert {n["id"] for n in updated} == {a["id"], b["id"]}
    assert _tag(db, a["id"]) == ["job", "urgent"]
    assert _tag(db, b["id"]) == ["job"]
    assert _tag(db, c["id"]) == ["home"]


def test_rename_into_existing_tag_merges_without_duplicates(db: Database) -> None:
    a = db.insert_note({"title": "A", "raw_text": "x", "tags": ["work", "work"]})
    b = db.insert_note({"title": "B", "raw_text": "y", "tags": ["work", "job"]})
    db.rename_tag("work", "job")
    assert _tag(db, a["id"]) == ["job"]
    assert _tag(db, b["id"]) == ["job"]


def test_merge_tags_folds_several_sources(db: Database) -> None:
    a = db.insert_note({"title": "A", "raw_text": "x", "tags": ["ai", "ml"]})
    b = db.insert_note({"title": "B", "raw_text": "y", "tags": ["ml"]})
    updated = db.merge_tags(["ai", "ml"], "artificial-intelligence")
    assert {n["id"] for n in updated} == {a["id"], b["id"]}
    assert _tag(db, a["id"]) == ["artificial-intelligence"]
    assert _tag(db, b["id"]) == ["artificial-intelligence"]
    tags = {t["tag"] for t in db.all_tags()}
    assert tags == {"artificial-intelligence"}


def test_delete_tag_keeps_notes(db: Database) -> None:
    a = db.insert_note({"title": "A", "raw_text": "x", "tags": ["junk", "keep"]})
    b = db.insert_note({"title": "B", "raw_text": "y", "tags": ["keep"]})
    updated = db.delete_tag("junk")
    assert {n["id"] for n in updated} == {a["id"]}
    assert _tag(db, a["id"]) == ["keep"]
    assert _tag(db, b["id"]) == ["keep"]
    assert db.get_note(a["id"]) is not None


def test_rewrite_leaves_fts_in_sync(db: Database) -> None:
    """Tags are indexed in FTS — a rename must reindex, or MATCH misses."""
    a = db.insert_note({"title": "A", "raw_text": "x", "tags": ["oldtag"]})
    assert db.search("tag:oldtag")
    db.rename_tag("oldtag", "newtag")
    assert db.search("tag:newtag")
    assert db.search("tag:oldtag") == []


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_tag_endpoints_publish_note_updated(client: TestClient, monkeypatch) -> None:
    r = client.post("/api/capture/text", json={"text": "note about hydras", "title": "Hydra"})
    note_id = r.json()["id"]
    client.patch(f"/api/notes/{note_id}", json={"tags": ["hydr"]})

    published: list[str] = []
    bus = client.app.state.st.bus
    orig = bus.publish
    monkeypatch.setattr(bus, "publish", lambda name, payload: (published.append(name), orig(name, payload)))

    resp = client.post("/api/tags/rename", json={"from_tag": "hydr", "to": "hydra"})
    assert resp.json()["updated"] == 1
    assert published.count("note.updated") == 1

    tags = client.get("/api/tags").json()
    assert {t["tag"] for t in tags} == {"hydra"}

    # Merge and delete endpoints publish the same way.
    client.post("/api/tags/merge", json={"from_tags": ["hydra"], "to": "cephalopod"})
    client.post("/api/tags/delete", json={"tag": "cephalopod"})
    assert published.count("note.updated") == 3


def test_tag_audit_endpoint_flags_problems(client: TestClient) -> None:
    client.post("/api/capture/text", json={"text": "a", "title": "one"})
    client.post("/api/capture/text", json={"text": "b", "title": "two"})
    # 'work' is popular, 'wrk' is rare and a likely misspelling, 'work2'
    # contains 'work'.
    notes = client.get("/api/notes", params={"limit": 50}).json()
    client.patch(f"/api/notes/{notes[0]['id']}", json={"tags": ["work"]})
    client.patch(f"/api/notes/{notes[1]['id']}", json={"tags": ["wrk", "work2"]})

    audit = client.get("/api/tags/audit").json()
    rare_tags = {r["tag"] for r in audit["rare"]}
    assert "wrk" in rare_tags and "work2" in rare_tags
    overlap_pairs = {frozenset(p["tags"]) for p in audit["overlapping"]}
    assert frozenset({"work", "work2"}) in overlap_pairs
    misspelt_pairs = {frozenset(p["tags"]) for p in audit["misspelt"]}
    assert frozenset({"work", "wrk"}) in misspelt_pairs
    # Every pair proposes a single target to merge into.
    for p in audit["overlapping"] + audit["misspelt"]:
        assert p["target"] in p["tags"]
