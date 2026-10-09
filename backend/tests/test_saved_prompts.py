"""#105 saved prompts ("recipes" you can rerun).

A saved prompt is a named question, not a script. The idea says "recipes you
can rerun" and that is deliberately the smaller thing: storing a prompt and
sending it is the whole feature, and a prompt that grew its own execution
semantics would be a second assistant.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database, new_id
from fleeting.services.prompts import (
    MAX_PROMPT_CHARS,
    create_prompt,
    delete_prompt,
    list_prompts,
    update_prompt,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def test_a_prompt_round_trips(db: Database) -> None:
    row = create_prompt(db, "Weekly review", "What shipped this week?")
    assert row["name"] == "Weekly review"
    assert row["body"] == "What shipped this week?"


def test_prompts_are_listed_newest_first(db: Database) -> None:
    first = create_prompt(db, "First", "a")
    second = create_prompt(db, "Second", "b")
    assert [p["id"] for p in list_prompts(db)] == [second["id"], first["id"]]


def test_a_named_prompt_can_be_searched(db: Database) -> None:
    create_prompt(db, "Weekly review", "what shipped")
    create_prompt(db, "Sourdough", "when to feed the starter")
    assert [p["name"] for p in list_prompts(db, q="weekly")] == ["Weekly review"]


def test_search_covers_the_body_too(db: Database) -> None:
    create_prompt(db, "A", "shipped this week")
    assert len(list_prompts(db, q="shipped")) == 1


def test_an_empty_name_is_refused(db: Database) -> None:
    with pytest.raises(ValueError):
        create_prompt(db, "   ", "body")


def test_an_empty_body_is_refused(db: Database) -> None:
    with pytest.raises(ValueError):
        create_prompt(db, "Name", "  ")


def test_a_body_is_truncated_rather_than_rejected(db: Database) -> None:
    """A pasted paragraph is a normal thing to paste; refuse nothing."""
    row = create_prompt(db, "Long", "x" * (MAX_PROMPT_CHARS + 500))
    assert len(row["body"]) <= MAX_PROMPT_CHARS


def test_updating_a_prompt_replaces_it(db: Database) -> None:
    row = create_prompt(db, "Name", "old body")
    updated = update_prompt(db, row["id"], name="New", body="new body")
    assert updated["name"] == "New"
    assert updated["body"] == "new body"


def test_updating_a_missing_prompt_is_none(db: Database) -> None:
    assert update_prompt(db, "nope", name="x", body="y") is None


def test_deleting_a_prompt_removes_it(db: Database) -> None:
    row = create_prompt(db, "Name", "body")
    assert delete_prompt(db, row["id"]) is True
    assert list_prompts(db) == []


def test_deleting_a_missing_prompt_is_false(db: Database) -> None:
    assert delete_prompt(db, "nope") is False


# ---- endpoints -----------------------------------------------------------


def test_prompt_crud_over_the_api(client) -> None:
    created = client.post("/api/prompts", json={"name": "Weekly", "body": "what shipped"})
    assert created.status_code == 200
    pid = created.json()["id"]

    assert [p["name"] for p in client.get("/api/prompts").json()] == ["Weekly"]
    assert client.get("/api/prompts", params={"q": "weekly"}).json()[0]["id"] == pid
    assert client.patch(f"/api/prompts/{pid}", json={"name": "Renamed", "body": "b"}).status_code == 200
    assert client.get("/api/prompts").json()[0]["name"] == "Renamed"
    assert client.delete(f"/api/prompts/{pid}").status_code == 200
    assert client.get("/api/prompts").json() == []


def test_an_empty_prompt_over_the_api_is_422(client) -> None:
    assert client.post("/api/prompts", json={"name": "", "body": "b"}).status_code == 422


def test_deleting_a_missing_prompt_over_the_api_is_404(client) -> None:
    assert client.delete(f"/api/prompts/{new_id()}").status_code == 404
