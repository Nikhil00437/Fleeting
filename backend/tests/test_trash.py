"""#274 trash: DELETE hides + is reversible, purge destroys, retention prunes."""

from __future__ import annotations

from conftest import wait_done


def _make_note(client, text: str = "trash me please") -> dict:
    r = client.post("/api/capture/text", json={"text": text})
    assert r.status_code == 200
    return wait_done(client, r.json()["id"])


def test_delete_trashes_and_restore_brings_back(client):
    note = _make_note(client)

    assert client.delete(f"/api/notes/{note['id']}").json()["ok"] is True

    # gone from the default listing and FTS search...
    assert client.get("/api/notes").json() == []
    assert client.get("/api/search", params={"q": "trash"}).json() == []
    # ...but present in the trash, with the row intact
    trash = client.get("/api/trash").json()
    assert [n["id"] for n in trash] == [note["id"]]
    assert trash[0]["trashed_at"] is not None
    assert client.get(f"/api/notes/{note['id']}").json()["trashed_at"] is not None

    r = client.post(f"/api/notes/{note['id']}/restore")
    assert r.status_code == 200
    assert r.json()["trashed_at"] is None
    assert [n["id"] for n in client.get("/api/notes").json()] == [note["id"]]
    assert client.get("/api/trash").json() == []


def test_trashed_notes_are_hidden_from_tags_and_stats(client):
    note = _make_note(client, "grocery list #shopping")
    wait_done(client, note["id"])
    client.delete(f"/api/notes/{note['id']}")

    assert client.get("/api/tags").json() == []
    stats = client.get("/api/stats").json()
    assert stats["total"] == 0


def test_purge_hard_deletes(client):
    note = _make_note(client)
    client.delete(f"/api/notes/{note['id']}")

    assert client.post(f"/api/notes/{note['id']}/purge").json()["ok"] is True
    assert client.get("/api/trash").json() == []
    assert client.get(f"/api/notes/{note['id']}").status_code == 404
    # purge publishes note.deleted, so the row is really gone, not trashed again
    st = client.app.state.st
    assert st.db.get_note(note["id"]) is None


def test_trash_empty_purges_everything(client):
    a = _make_note(client, "first")
    b = _make_note(client, "second")
    client.delete(f"/api/notes/{a['id']}")
    client.delete(f"/api/notes/{b['id']}")

    assert client.post("/api/trash/empty").json()["purged"] == 2
    assert client.get("/api/trash").json() == []
    assert client.get(f"/api/notes/{a['id']}").status_code == 404


def test_retention_purge_respects_the_window(client, monkeypatch):
    from fleeting.db import now_iso

    note = _make_note(client, "ancient history")
    client.delete(f"/api/notes/{note['id']}")

    # Pretend the trash happened long ago, then run the boot purge path.
    client.app.state.st.db.update_note(note["id"], {"trashed_at": "2020-01-01T00:00:00+00:00"})

    from fleeting.main import create_app  # noqa: F401  (lifespan already ran)

    st = client.app.state.st
    purged = st.db.purge_expired_trash(retention_days=30, audio_root=st.cfg_audio_dir())
    assert [n["id"] for n in purged] == [note["id"]]

    # A freshly trashed note survives the same purge.
    fresh = _make_note(client, "recent history")
    client.delete(f"/api/notes/{fresh['id']}")
    st.db.update_note(fresh["id"], {"trashed_at": now_iso()})
    assert st.db.purge_expired_trash(30) == []


def test_config_section_round_trips(client):
    """notes.trash_retention_days must survive a config save/load cycle."""
    import fleeting.config as fcfg

    cfg = fcfg.load_config()
    assert cfg.notes.trash_retention_days == 30
    cfg.notes.trash_retention_days = 7
    fcfg.save_config(cfg)
    assert fcfg.load_config().notes.trash_retention_days == 7
