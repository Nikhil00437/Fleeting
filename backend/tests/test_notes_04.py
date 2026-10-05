"""0.4 note features: star (#273), snooze (#14), sensitive (#26)."""

from __future__ import annotations

from conftest import wait_done


def _note(client, text: str = "organise me") -> dict:
    r = client.post("/api/capture/text", json={"text": text})
    return wait_done(client, r.json()["id"])


# ---- #273 star -----------------------------------------------------------

def test_star_toggles_and_filters(client):
    note = _note(client, "star quality")

    assert client.post(f"/api/notes/{note['id']}/star").json()["starred"] is True
    assert [n["id"] for n in client.get("/api/notes", params={"starred": "true"}).json()] == [
        note["id"]
    ]
    assert client.post(f"/api/notes/{note['id']}/star").json()["starred"] is False
    assert client.get("/api/notes", params={"starred": "true"}).json() == []


# ---- #14 snooze ----------------------------------------------------------

def test_snooze_hides_until_stamp_passes(client):
    from fleeting.db import now_iso

    note = _note(client, "remind me later")
    st = client.app.state.st

    r = client.post(f"/api/notes/{note['id']}/snooze", json={"until": "tomorrow"})
    assert r.status_code == 200
    assert r.json()["snoozed_until"] is not None
    # hidden from the default listing...
    assert client.get("/api/notes").json() == []
    # ...but visible in the snoozed view with its wake stamp
    snoozed = client.get("/api/notes/snoozed").json()
    assert [n["id"] for n in snoozed] == [note["id"]]

    # a stamp in the past wakes the note without touching it
    st.db.update_note(note["id"], {"snoozed_until": "2020-01-01T00:00:00+00:00"})
    assert [n["id"] for n in client.get("/api/notes").json()] == [note["id"]]
    assert client.get("/api/notes/snoozed").json() == []

    # freshly re-snoozed, then explicitly woken via empty body
    client.post(f"/api/notes/{note['id']}/snooze", json={"until": "next_monday"})
    assert client.get("/api/notes").json() == []
    r = client.post(f"/api/notes/{note['id']}/snooze", json={})
    assert r.json()["snoozed_until"] is None
    assert [n["id"] for n in client.get("/api/notes").json()] == [note["id"]]


def test_snooze_presets_and_validation(client):
    note = _note(client, "snooze shapes")

    r = client.post(f"/api/notes/{note['id']}/snooze", json={"until": "later"})
    later = r.json()["snoozed_until"]
    assert later.endswith("+00:00") or later.endswith("Z")

    r = client.post(f"/api/notes/{note['id']}/snooze", json={"until": "2030-01-02"})
    assert r.json()["snoozed_until"].startswith("2030-01-02T")

    assert client.post(
        f"/api/notes/{note['id']}/snooze", json={"until": "sometime maybe"}
    ).status_code == 422


# ---- #26 sensitive -------------------------------------------------------

def test_sensitive_note_skips_vault_mirror(client, tmp_path):
    import time

    from fleeting.services import markdown as md

    note = _note(client, "private: my tax numbers and passwords")
    st = client.app.state.st
    assert client.patch(f"/api/notes/{note['id']}", json={"sensitive": True}).json()["sensitive"] is True

    assert md.sync_note(st.cfg.paths, st.db.get_note(note["id"])) is None
    # no file appeared anywhere in the vault
    vault = tmp_path / "vault"
    assert not any(vault.rglob("*.md")) if vault.exists() else True

    # and a file written *before* the flag is cleaned up on the next sync
    note2 = _note(client, "later marked private")
    md.sync_note(st.cfg.paths, st.db.get_note(note2["id"]))
    path = md.vault_path_for(st.cfg.paths, st.db.get_note(note2["id"]))
    assert path.exists()
    client.patch(f"/api/notes/{note2['id']}", json={"sensitive": True})
    md.sync_note(st.cfg.paths, st.db.get_note(note2["id"]))
    assert not path.exists()


def test_sensitive_note_enriches_without_the_llm(client, monkeypatch):
    note = _note(client, "secret project codename hedgehog")
    st = client.app.state.st
    client.patch(f"/api/notes/{note['id']}", json={"sensitive": True})

    # force the LLM path to prove it is never called for sensitive notes
    called = []

    async def boom(*args, **kwargs):
        called.append(True)
        raise AssertionError("llm.enrich must not run for sensitive notes")

    import fleeting.services.llm as llm

    monkeypatch.setattr(llm, "enrich", boom)

    client.post(f"/api/notes/{note['id']}/reprocess")
    fresh = wait_done(client, note["id"])
    assert fresh["status"] == "done"
    assert fresh["source"]["enrichment"] == "heuristic-sensitive"
    assert not called
    # and no embedding vector was written either
    assert st.db.get_note_embedding(note["id"]) is None


def test_sensitive_note_excluded_from_assistant_context(client):
    from fleeting.services.assistant import build_assistant_context

    note = _note(client, "hidden from the assistant hedgehog")
    client.patch(f"/api/notes/{note['id']}", json={"sensitive": True})

    st = client.app.state.st
    _ctx_text, sources, _used = build_assistant_context("hedgehog", st.db, st.cfg)
    ids = {s["id"] for s in sources if s.get("kind") == "note"}
    assert note["id"] not in ids


# ---- #474 review state + #424 review queue -------------------------------

def test_heuristic_enrichment_lands_in_the_review_queue(client):
    """No LLM in tests, so every capture enriches heuristically -> 'raw'."""
    note = _note(client, "queue me for review")
    assert note["review_state"] == "raw"
    assert [n["id"] for n in client.get("/api/notes", params={"review_state": "raw"}).json()] == [
        note["id"]
    ]
    # a human review promotes it and empties the queue
    r = client.patch(f"/api/notes/{note['id']}", json={"review_state": "reviewed"})
    assert r.json()["review_state"] == "reviewed"
    assert client.get("/api/notes", params={"review_state": "raw"}).json() == []


# ---- #19 version history + revert ----------------------------------------

def test_edits_snapshot_previous_content(client):
    note = _note(client, "history begins here")
    client.patch(f"/api/notes/{note['id']}", json={"raw_text": "second version of the text"})
    client.patch(f"/api/notes/{note['id']}", json={"raw_text": "third version", "title": "renamed"})

    versions = client.get(f"/api/notes/{note['id']}/versions").json()
    # 1: pre-enrichment (raw capture, no title/summary yet), 2-3: the two edits
    assert len(versions) == 3
    # oldest first: every snapshot keeps the original raw capture
    assert versions[0]["raw_text"].startswith("history begins here")
    assert versions[0]["title"] == ""  # enrichment had not landed yet
    assert versions[1]["origin"] == "edit"
    assert versions[2]["raw_text"] == "second version of the text"

    # bookkeeping-only updates (pin, status) must not fabricate history
    client.post(f"/api/notes/{note['id']}/pin")
    assert len(client.get(f"/api/notes/{note['id']}/versions").json()) == 3


def test_revert_restores_and_is_itself_undoable(client):
    note = _note(client, "original text to keep")
    client.patch(f"/api/notes/{note['id']}", json={"raw_text": "oops destroyed"})

    original = client.get(f"/api/notes/{note['id']}/versions").json()[0]
    r = client.post(f"/api/notes/{note['id']}/versions/{original['id']}/revert")
    assert r.status_code == 200
    assert r.json()["raw_text"].startswith("original text to keep")

    # the revert appended a history entry holding the destroyed text
    versions = client.get(f"/api/notes/{note['id']}/versions").json()
    assert versions[-1]["raw_text"] == "oops destroyed"
    assert versions[-1]["origin"] == "edit"

    assert client.post(
        f"/api/notes/{note['id']}/versions/999999/revert"
    ).status_code == 404


# ---- #20 regenerate ------------------------------------------------------

def test_regenerate_requires_a_provider(client):
    note = _note(client, "regenerate me")
    r = client.post(f"/api/notes/{note['id']}/regenerate", json={})
    assert r.status_code == 400
    assert "no LLM provider" in r.json()["detail"]
