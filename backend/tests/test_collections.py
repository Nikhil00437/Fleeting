"""Collections: one CRUD for manual, saved_query and project kinds (#267-269)."""

from __future__ import annotations

from conftest import wait_done


def _note(client, text: str, title: str | None = None) -> dict:
    r = client.post("/api/capture/text", json={"text": text})
    note = wait_done(client, r.json()["id"])
    if title:
        note = client.patch(f"/api/notes/{note['id']}", json={"title": title}).json()
    return note


def test_create_list_get_round_trip(client):
    r = client.post(
        "/api/collections",
        json={"name": "Home reno", "kind": "project", "description": "balcony + study"},
    )
    assert r.status_code == 200
    coll = r.json()
    assert coll["kind"] == "project"

    listed = client.get("/api/collections").json()
    assert [c["name"] for c in listed] == ["Home reno"]
    assert listed[0]["item_count"] == 0

    detail = client.get(f"/api/collections/{coll['id']}").json()
    assert detail["description"] == "balcony + study"
    assert detail["notes"] == []

    assert client.patch(
        f"/api/collections/{coll['id']}", json={"status": "active", "name": "Home renovation"}
    ).json()["name"] == "Home renovation"


def test_manual_membership_orders_and_removes(client):
    a = _note(client, "first entry", title="Alpha")
    b = _note(client, "second entry", title="Beta")
    coll = client.post("/api/collections", json={"name": "playlist"}).json()

    assert client.post(f"/api/collections/{coll['id']}/notes", json={"note_id": a["id"]}).json()["ok"]
    client.post(f"/api/collections/{coll['id']}/notes", json={"note_id": b["id"]})
    # re-adding is idempotent
    client.post(f"/api/collections/{coll['id']}/notes", json={"note_id": a["id"]})

    detail = client.get(f"/api/collections/{coll['id']}").json()
    assert [n["id"] for n in detail["notes"]] == [a["id"], b["id"]]

    client.delete(f"/api/collections/{coll['id']}/notes/{a['id']}")
    detail = client.get(f"/api/collections/{coll['id']}").json()
    assert [n["id"] for n in detail["notes"]] == [b["id"]]


def test_trashed_notes_drop_out_of_manual_collections(client):
    a = _note(client, "keep me", title="Keeper")
    b = _note(client, "bin me", title="Binner")
    coll = client.post("/api/collections", json={"name": "mixed"}).json()
    client.post(f"/api/collections/{coll['id']}/notes", json={"note_id": a["id"]})
    client.post(f"/api/collections/{coll['id']}/notes", json={"note_id": b["id"]})

    client.delete(f"/api/notes/{b['id']}")
    detail = client.get(f"/api/collections/{coll['id']}").json()
    assert [n["id"] for n in detail["notes"]] == [a["id"]]


def test_saved_query_executes_live(client):
    client.post(
        "/api/collections",
        json={
            "name": "voice memos",
            "kind": "saved_query",
            "query": {"type": "voice"},
        },
    )
    _note(client, "plain text note")
    _note(client, "another text note")

    detail = client.get("/api/collections").json()
    assert detail[0]["kind"] == "saved_query"

    full = client.get(f"/api/collections/{detail[0]['id']}").json()
    # no voice captures exist; the query matched nothing but stayed valid
    assert full["notes"] == []


def test_saved_query_by_tag_tracks_future_notes(client):
    coll = client.post(
        "/api/collections",
        json={"name": "recipes", "kind": "saved_query", "query": {"tag": "cooking"}},
    ).json()

    n = _note(client, "tomato soup basics")
    client.patch(f"/api/notes/{n['id']}", json={"tags": ["cooking"]})

    full = client.get(f"/api/collections/{coll['id']}").json()
    assert [x["id"] for x in full["notes"]] == [n["id"]]


def test_unknown_kind_rejected(client):
    assert client.post(
        "/api/collections", json={"name": "bad", "kind": "galaxy"}
    ).status_code == 422


def test_delete_collection(client):
    coll = client.post("/api/collections", json={"name": "temp"}).json()
    assert client.delete(f"/api/collections/{coll['id']}").json()["ok"] is True
    assert client.get(f"/api/collections/{coll['id']}").status_code == 404
    assert client.delete(f"/api/collections/{coll['id']}").status_code == 404
