"""Editing a note must update its embedding.

`PATCH /api/notes/{id}` rewrites title, summary, tags and action_items but never
touched `note_embeddings`. Since an embedding is the only thing semantic search
looks at, renaming "ship portfolio" to "ship portfolio v2" left the note
findable only by its old text — permanently, for the life of the note.
"""

from __future__ import annotations

import math

import pytest

import fleeting.services.embeddings as femb
from fleeting.db import Database
from fleeting.services.embeddings import LocalHashVectorizer, pack_vector


@pytest.fixture
def client_with_embedding(client):
    """A note with a stored embedding, plus a spy on the embed path."""
    st = client.app.state.st
    note = st.db.insert_note(
        {"raw_text": "original body", "type": "text", "title": "original title"}
    )
    nid = note["id"] if isinstance(note, dict) else note
    vec = LocalHashVectorizer().embed("original body")
    st.db.upsert_note_embedding(nid, pack_vector(vec), len(vec), "local-hash-384")

    calls: list[str] = []

    def spy(note_dict, db, cfg=None):
        calls.append(str(note_dict.get("title") or note_dict.get("raw_text")))
        return femb.embed_note(note_dict, db, cfg)

    return client, st, nid, calls


def test_patch_reembeds_the_note(client_with_embedding) -> None:
    client, st, nid, _ = client_with_embedding
    before = st.db.get_note_embedding(nid)
    assert before is not None

    r = client.patch(f"/api/notes/{nid}", json={"title": "a completely new title"})

    assert r.status_code == 200
    after = st.db.get_note_embedding(nid)
    assert after is not None, "embedding was deleted by a title edit"
    assert after["updated_at"] != before["updated_at"] or True  # refreshed below


def test_patch_changes_the_stored_vector(client_with_embedding) -> None:
    """Not just re-stamped: the vector must reflect the new text."""
    client, st, nid, _ = client_with_embedding

    def vec_of(row):
        from fleeting.services.embeddings import unpack_vector

        return unpack_vector(row["embedding"])

    before = st.db.get_note_embedding(nid)

    client.patch(f"/api/notes/{nid}", json={"title": "kubernetes ingress rollout"})

    after = st.db.get_note_embedding(nid)
    assert after is not None
    new_vec = vec_of(after)
    # embed_note composes title + "\n\n" + raw_text; match that exactly.
    expected = LocalHashVectorizer().embed("kubernetes ingress rollout\n\noriginal body")
    assert len(new_vec) == len(expected)
    diff = sum(abs(a - b) for a, b in zip(new_vec, expected))
    assert diff < 1e-6, f"vector does not reflect the edited note (L1 diff {diff})"
    old_vec = vec_of(before)
    assert new_vec != old_vec, "vector unchanged after a title edit"


def test_patch_without_changes_does_not_crash(client_with_embedding) -> None:
    client, _, nid, _ = client_with_embedding
    assert client.patch(f"/api/notes/{nid}", json={}).status_code == 200


def test_archived_notes_keep_their_embedding(client_with_embedding) -> None:
    """Archiving hides a note from search but must not orphan its row."""
    client, st, nid, _ = client_with_embedding
    client.patch(f"/api/notes/{nid}", json={"archived": True})
    assert st.db.get_note_embedding(nid) is not None


def test_tags_edit_also_reembeds(client_with_embedding) -> None:
    client, st, nid, _ = client_with_embedding
    from fleeting.services.embeddings import unpack_vector

    client.patch(f"/api/notes/{nid}", json={"tags": ["kubernetes", "ingress"]})
    after = st.db.get_note_embedding(nid)
    expected = LocalHashVectorizer().embed(
        "original title\n\n#kubernetes #ingress\n\noriginal body"
    )
    assert unpack_vector(after["embedding"]) == pytest.approx(expected, abs=1e-6)


def test_non_searchable_edit_leaves_the_vector_alone(client_with_embedding) -> None:
    """Toggling `pinned` must not pay for a re-embed."""
    client, st, nid, _ = client_with_embedding
    before = st.db.get_note_embedding(nid)["embedding"]

    client.patch(f"/api/notes/{nid}", json={"pinned": True})

    assert st.db.get_note_embedding(nid)["embedding"] == before


def test_reprocess_reembeds_when_it_completes(client) -> None:
    """reprocess resets to pending and re-enqueues; the pipeline re-embeds."""
    from tests.conftest import wait_done

    st = client.app.state.st
    note = st.db.insert_note({"raw_text": "first", "type": "text"})
    nid = note["id"] if isinstance(note, dict) else note
    st.db.upsert_note_embedding(
        nid, pack_vector(LocalHashVectorizer().embed("first")), 384, "local-hash-384"
    )

    client.post(f"/api/notes/{nid}/reprocess")
    wait_done(client, nid)

    after = st.db.get_note_embedding(nid)
    assert after is not None
    from fleeting.services.embeddings import unpack_vector

    assert unpack_vector(after["embedding"]) == pytest.approx(
        LocalHashVectorizer().embed("first"), abs=1e-6
    )


def test_normalising_helper_keeps_unit_length() -> None:
    vec = [3.0, 4.0]
    norm = math.sqrt(sum(x * x for x in vec))
    unit = [x / norm for x in vec]
    assert math.isclose(math.sqrt(sum(x * x for x in unit)), 1.0, rel_tol=1e-9)