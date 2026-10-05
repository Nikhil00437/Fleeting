"""capture_id idempotency (#332) + source_title plumbing (#3)."""

from __future__ import annotations


def test_duplicate_capture_id_returns_existing_note(client):
    r1 = client.post(
        "/api/capture/text",
        json={"text": "hello world", "capture_id": "abc123", "source_title": "My Editor"},
    )
    assert r1.status_code == 200
    note1 = r1.json()
    assert note1["capture_id"] == "abc123"
    assert note1["source_title"] == "My Editor"

    # same capture_id, different text (e.g. client retry): no new note
    r2 = client.post(
        "/api/capture/text",
        json={"text": "hello world", "capture_id": "abc123"},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == note1["id"]

    notes = client.get("/api/notes").json()
    assert len([n for n in notes if n["capture_id"] == "abc123"]) == 1


def test_distinct_capture_ids_create_distinct_notes(client):
    client.post("/api/capture/text", json={"text": "one", "capture_id": "a"})
    client.post("/api/capture/text", json={"text": "two", "capture_id": "b"})
    client.post("/api/capture/text", json={"text": "three"})
    notes = client.get("/api/notes").json()
    assert len(notes) == 3


def test_capture_id_on_youtube(client):
    r1 = client.post("/api/capture/youtube", json={"url": "https://youtu.be/abc123XYZ99", "capture_id": "yt1"})
    r2 = client.post("/api/capture/youtube", json={"url": "https://youtu.be/abc123XYZ99", "capture_id": "yt1"})
    assert r1.json()["id"] == r2.json()["id"]
