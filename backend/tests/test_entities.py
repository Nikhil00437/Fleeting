"""#411 a people index built from names in notes.

Capitalised-run extraction is crude, and that is the point: it is
deterministic, it runs on every note for free, and it can be corrected
later (#414 alias merging). An LLM pass per note would be neither free nor
correctable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.entities import extract_people, people_index, mention_counts


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


# ---- extraction ----------------------------------------------------------


def test_a_name_in_the_middle_of_a_sentence_is_found() -> None:
    assert extract_people("Shipped the fix after Priya reviewed it.") == ["Priya"]


def test_a_name_at_the_start_of_a_sentence_is_found() -> None:
    assert extract_people("Priya reviewed the router change.") == ["Priya"]


def test_two_word_names_are_found() -> None:
    assert extract_people("Met with Arjun Mehta about pricing.") == ["Arjun Mehta"]


def test_lowercase_words_are_not_names() -> None:
    assert extract_people("the router is broken") == []


def test_a_sentence_start_capitalised_word_is_not_a_name_on_its_own() -> None:
    """'The bridge network broke' is not a person called 'The'."""
    assert extract_people("The bridge network broke after the upgrade.") == []


def test_days_and_months_are_not_people() -> None:
    assert extract_people("Monday we ship, in December, per Tom") == ["Tom"]


def test_common_product_names_are_not_people() -> None:
    assert extract_people("Deployed to GitHub and opened a Docker issue.") == []


def test_camel_case_yields_no_name_at_all() -> None:
    """'GitHub' must not become 'Git' or 'Hub' — no stoplist can cover these."""
    assert extract_people("OpenAI and JavaScript both shipped.") == []


def test_an_initial_is_part_of_the_name() -> None:
    assert extract_people("Ben C. called.") == ["Ben C."]


def test_names_are_deduped_and_keep_first_seen_order() -> None:
    found = extract_people("Priya and Tom. Priya again. Tom again.")
    assert found == ["Priya", "Tom"]


def test_empty_text_yields_nothing() -> None:
    assert extract_people("") == []


def test_a_trailing_period_is_not_part_of_the_name() -> None:
    assert extract_people("Ask Priya.") == ["Priya"]


def test_a_possessive_is_stripped() -> None:
    assert extract_people("Priya's notes") == ["Priya"]


# ---- the index -----------------------------------------------------------


def test_the_index_counts_mentions_per_person(db: Database) -> None:
    db.insert_note({"title": "a", "raw_text": "Priya reviewed it.", "type": "text"})
    db.insert_note({"title": "b", "raw_text": "Priya and Priya again.", "type": "text"})
    assert mention_counts(db)["Priya"] == 3


def test_the_index_reports_the_last_mention(db: Database) -> None:
    """#412: 'last mentioned' is what makes a stale contact visible."""
    old = db.insert_note({
        "title": "old", "raw_text": "Priya reviewed it.", "type": "text",
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    db.insert_note({
        "title": "new", "raw_text": "Priya again.", "type": "text",
        "created_at": "2026-06-01T00:00:00+00:00",
    })
    people = {p["name"]: p for p in people_index(db)}
    assert people["Priya"]["last_seen"] == "2026-06-01"
    assert people["Priya"]["first_seen"] == "2026-01-01"
    assert people["Priya"]["notes_count"] == 2


def test_the_index_ignores_trashed_notes(db: Database) -> None:
    db.insert_note({"title": "a", "raw_text": "Priya reviewed it.", "type": "text"})
    db.execute("UPDATE notes SET trashed_at = '2026-10-09T00:00:00Z'")
    db.commit()
    assert mention_counts(db) == {}


def test_the_index_ignores_sensitive_notes(db: Database) -> None:
    """#26: a person's name in a sensitive note is not a public contact."""
    db.insert_note({"title": "a", "raw_text": "Priya's password is x.", "type": "text", "sensitive": 1})
    assert mention_counts(db) == {}


def test_the_index_is_sorted_by_mentions(db: Database) -> None:
    db.insert_note({"title": "a", "raw_text": "Priya and Tom and Ada.", "type": "text"})
    db.insert_note({"title": "b", "raw_text": "Priya again.", "type": "text"})
    # Ties break alphabetically so the list does not reshuffle between calls.
    assert [p["name"] for p in people_index(db)] == ["Priya", "Ada", "Tom"]


def test_mentions_and_notes_count_differ(db: Database) -> None:
    """One note mentioning Priya twice is two mentions and one note."""
    db.insert_note({"title": "a", "raw_text": "Priya and Priya again.", "type": "text"})
    entry = people_index(db)[0]
    assert entry["mentions"] == 2
    assert entry["notes_count"] == 1


@pytest.mark.anyio
async def test_index_endpoint_lists_people(client) -> None:
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    r = client.get("/api/entities/people")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    assert "Priya" in names


@pytest.mark.anyio
async def test_people_endpoint_exposes_last_seen(client) -> None:
    """#412 rides on the same row as the count — no second query."""
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    people = client.get("/api/entities/people").json()
    assert people[0]["last_seen"]


@pytest.mark.anyio
async def test_person_page_lists_their_notes(client) -> None:
    """#413: one person's notes, reachable without a search query."""
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    client.post("/api/capture/text", json={"text": "Unrelated note about sourdough."})
    r = client.get("/api/entities/people/Priya/notes")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert "Priya" in r.json()[0]["raw_text"]


@pytest.mark.anyio
async def test_person_page_404s_for_someone_never_mentioned(client) -> None:
    client.post("/api/capture/text", json={"text": "Priya reviewed the router change."})
    assert client.get("/api/entities/people/Nobody/notes").status_code == 404


def test_people_index_includes_pending_notes(db: Database) -> None:
    """A note awaiting enrichment still has a body and still names people."""
    note = db.insert_note({"title": "t", "raw_text": "Priya called.", "type": "text"})
    assert db.get_note(note["id"])["status"] == "pending"
    assert [p["name"] for p in people_index(db)] == ["Priya"]
