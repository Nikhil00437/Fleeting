"""#111 assistant conversation history: save, search, pin, delete."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.chatlog import list_chats, save_chat, title_of


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def thread(*turns: tuple[str, str]) -> list[dict]:
    msgs: list[dict] = []
    for role, content in turns:
        msgs.append({"role": role, "content": content})
    return msgs


def test_saved_conversation_round_trips_messages(db: Database) -> None:
    saved = save_chat(db, "c1", thread(("user", "what did I ship?"), ("assistant", "the router")))
    assert saved["title"] == "what did I ship?"
    assert [m["content"] for m in saved["messages"]] == ["what did I ship?", "the router"]


def test_saving_again_updates_rather_than_duplicates(db: Database) -> None:
    save_chat(db, "c1", thread(("user", "first"), ("assistant", "a")))
    save_chat(db, "c1", thread(("user", "first"), ("assistant", "a"), ("user", "second")))
    assert len(list_chats(db)) == 1
    assert len(list_chats(db)[0]["messages"]) == 3


def test_empty_transcript_is_not_stored(db: Database) -> None:
    assert save_chat(db, "c1", [])["messages"] == []
    assert list_chats(db) == []


def test_system_and_empty_messages_are_dropped(db: Database) -> None:
    saved = save_chat(db, "c1", [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": ""}])
    assert [m["content"] for m in saved["messages"]] == ["hi"]


def test_search_matches_the_transcript_not_just_the_title(db: Database) -> None:
    save_chat(db, "c1", thread(("user", "what did I ship?"), ("assistant", "the router migration")))
    save_chat(db, "c2", thread(("user", "recipes?"), ("assistant", "dal tadka")))

    hits = list_chats(db, q="router")
    assert [c["id"] for c in hits] == ["c1"]
    assert hits[0]["preview"].startswith("the router migration")
    assert hits[0]["hit_count"] == 1


def test_pinned_threads_sort_first_and_can_be_filtered(db: Database) -> None:
    save_chat(db, "old", thread(("user", "older thread")))
    save_chat(db, "keep", thread(("user", "important thread")))

    from fleeting.services.chatlog import set_pinned

    set_pinned(db, "keep", True)
    assert [c["id"] for c in list_chats(db)] == ["keep", "old"]
    assert [c["id"] for c in list_chats(db, pinned_only=True)] == ["keep"]


def test_unpinning_and_deleting(db: Database) -> None:
    from fleeting.services.chatlog import delete_chat, set_pinned

    save_chat(db, "c1", thread(("user", "hi")))
    set_pinned(db, "c1", False)
    assert list_chats(db)[0]["pinned"] == 0
    assert delete_chat(db, "c1") is True
    assert delete_chat(db, "c1") is False
    assert list_chats(db) == []


def test_title_falls_back_to_the_first_assistant_line() -> None:
    assert title_of([{"role": "assistant", "content": "just the answer"}]) == "just the answer"
    assert title_of([]) == "Empty conversation"
    assert title_of([{"role": "user", "content": "x" * 200}]).endswith("…")


def test_unreadable_transcript_does_not_break_the_list(db: Database) -> None:
    save_chat(db, "c1", thread(("user", "hi")))
    db.execute("UPDATE assistant_chats SET messages = 'not json' WHERE id = 'c1'")
    db.commit()
    assert list_chats(db)[0]["messages"] == []


# --- HTTP surface -----------------------------------------------------------


def test_history_endpoints(client) -> None:
    client.post("/api/assistant/history/h1", json={"messages": thread(("user", "router please"), ("assistant", "done"))})

    listing = client.get("/api/assistant/history").json()
    assert [c["id"] for c in listing] == ["h1"]

    assert client.get("/api/assistant/history?q=router").json()[0]["id"] == "h1"
    assert client.get("/api/assistant/history?q=zzz").json() == []

    assert client.patch("/api/assistant/history/h1", json={"pinned": True}).json()["pinned"] == 1
    assert client.get("/api/assistant/history?pinned_only=true").json()[0]["id"] == "h1"

    assert client.delete("/api/assistant/history/h1").status_code == 204
    assert client.get("/api/assistant/history").json() == []


def test_history_404s(client) -> None:
    assert client.patch("/api/assistant/history/nope", json={"pinned": True}).status_code == 404
    assert client.delete("/api/assistant/history/nope").status_code == 404