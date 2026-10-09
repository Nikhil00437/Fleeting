"""#108 assistant suggestions inside the note drawer.

Contextual, not the generic starter chips: the suggestions are about *this*
note. #26 applies with full force — a sensitive note must produce no
suggestion at all, because a suggestion is derived from the note's text.
"""

from __future__ import annotations

import pytest

from fleeting.db import Database
from fleeting.services.assistant import note_suggestions


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def test_a_note_with_actions_suggests_following_them_up(db: Database) -> None:
    note = db.insert_note({
        "title": "Router", "raw_text": "todo: reflash the router",
        "action_items": [{"text": "Reflash the router", "priority": "P2"}],
        "status": "done",
    })
    out = note_suggestions(db, note["id"])
    assert any("Reflash the router" in s for s in out)


def test_suggestions_are_about_this_note(db: Database) -> None:
    a = db.insert_note({"title": "Sourdough", "raw_text": "feed the starter", "status": "done"})
    db.insert_note({"title": "Router", "raw_text": "reflash it", "status": "done"})
    out = note_suggestions(db, a["id"])
    assert all("Router" not in s for s in out)


def test_a_sensitive_note_produces_no_suggestions(db: Database) -> None:
    """A suggestion is derived from the note text; the note must not leak."""
    note = db.insert_note({
        "title": "Wifi", "raw_text": "the wifi passphrase is swordfish",
        "action_items": [{"text": "Change the passphrase"}],
        "sensitive": 1, "status": "done",
    })
    assert note_suggestions(db, note["id"]) == []


def test_a_trashed_note_produces_no_suggestions(db: Database) -> None:
    note = db.insert_note({
        "title": "Gone", "raw_text": "x", "action_items": [{"text": "y"}], "status": "done",
    })
    db.execute("UPDATE notes SET trashed_at = '2026-10-09T00:00:00Z' WHERE id = ?", (note["id"],))
    db.commit()
    assert note_suggestions(db, note["id"]) == []


def test_a_missing_note_produces_no_suggestions(db: Database) -> None:
    assert note_suggestions(db, "nope") == []


def test_there_is_always_something_to_ask(db: Database) -> None:
    note = db.insert_note({"title": "Plain", "raw_text": "just a thought", "status": "done"})
    assert note_suggestions(db, note["id"])


def test_the_list_is_bounded(db: Database) -> None:
    note = db.insert_note({
        "title": "Busy",
        "raw_text": "x",
        "action_items": [{"text": f"Task {i}"} for i in range(20)],
        "status": "done",
    })
    assert len(note_suggestions(db, note["id"])) <= 4


def test_people_in_a_note_are_offered_as_a_question(db: Database) -> None:
    note = db.insert_note({
        "title": "Call", "raw_text": "Priya asked about the contract",
        "status": "done",
    })
    out = note_suggestions(db, note["id"])
    assert any("Priya" in s for s in out)


# ---- endpoint ------------------------------------------------------------


def test_endpoint_returns_suggestions_for_one_note(client) -> None:
    note_id = client.post(
        "/api/capture/text", json={"text": "todo: reflash the router"}
    ).json()["id"]
    r = client.get(f"/api/assistant/note-suggestions", params={"note_id": note_id})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_endpoint_for_a_sensitive_note_is_empty(client) -> None:
    note_id = client.post(
        "/api/capture/text", json={"text": "the passphrase is swordfish"}
    ).json()["id"]
    client.patch(f"/api/notes/{note_id}", json={"sensitive": True})
    r = client.get(f"/api/assistant/note-suggestions", params={"note_id": note_id})
    assert r.json() == []


def test_endpoint_without_a_note_id_is_422(client) -> None:
    assert client.get("/api/assistant/note-suggestions").status_code == 422
