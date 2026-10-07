"""#319 transcript search with word-timestamp hits."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import wait_done

from fleeting.db import Database
from fleeting.services.transcript_search import transcript_search, word_hits


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _voice(db: Database, title: str, words: list[tuple[str, float]], **extra) -> dict:
    return db.insert_note({
        "type": "voice",
        "title": title,
        "raw_text": " ".join(w for w, _ in words),
        "audio_path": "/data/audio/x.webm",
        "source": {
            "transcription": {
                "words": [{"w": w, "s": s, "e": s + 0.4} for w, s in words],
                "duration": words[-1][1] + 0.4 if words else 0,
            }
        },
        **extra,
    })


WORDS = [
    ("remember", 0.0), ("to", 0.5), ("reset", 1.0), ("the", 1.5),
    ("router", 2.0), ("password", 2.5), ("before", 3.0), ("friday", 3.5),
]


def test_word_hits_terms_and_context() -> None:
    words = [{"w": w, "s": s, "e": s + 0.4} for w, s in WORDS]
    hits = word_hits(words, ["router"], [])
    assert len(hits) == 1
    assert hits[0]["t"] == 2.0
    assert "reset the router password" in hits[0]["text"]


def test_word_hits_phrase_across_words() -> None:
    words = [{"w": w, "s": s, "e": s + 0.4} for w, s in WORDS]
    hits = word_hits(words, [], ["reset the router"])
    assert hits[0]["t"] == 1.0


def test_word_hits_no_match_or_empty() -> None:
    words = [{"w": w, "s": s, "e": s + 0.4} for w, s in WORDS]
    assert word_hits(words, ["zebra"], []) == []
    assert word_hits([], ["router"], []) == []


def test_transcript_search_returns_notes_with_timestamps(db: Database) -> None:
    _voice(db, "Router memo", WORDS)
    _voice(db, "Groceries", [("milk", 0.0), ("eggs", 1.0), ("bread", 2.0)])
    results = transcript_search(db, "router password")
    assert len(results) == 1
    assert results[0]["note"]["title"] == "Router memo"
    assert results[0]["hits"][0]["t"] == 2.0
    # Type filter operator narrows like anywhere else.
    assert transcript_search(db, "router password type:text") == []


def test_transcript_search_skips_archived_and_text_notes(db: Database) -> None:
    _voice(db, "Router memo", WORDS)
    archived = _voice(db, "Old router memo", WORDS, archived=1)
    results = transcript_search(db, "router")
    assert all(r["note"]["id"] != archived["id"] for r in results)


def test_transcript_api_endpoint(client: TestClient) -> None:
    # PATCH cannot set type/source (by design), so seed the voice note via db.
    db = client.app.state.st.db
    _voice(db, "Fork sync", [("sync", 0.0), ("the", 0.5), ("fork", 1.0), ("upstream", 1.5)])

    res = client.get("/api/search/transcript", params={"q": "fork"}).json()
    assert len(res) == 1
    assert res[0]["hits"][0]["t"] == 1.0
    assert client.get("/api/search/transcript", params={"q": ""}).json() == []
