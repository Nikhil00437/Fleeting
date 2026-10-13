"""#455: counts and samples before anything bulk gets destroyed.

Written after an endpoint that purges every trashed note was called as a probe
and did exactly that. One note, already in the trash, gone for good. The failure
was not that the endpoint was dangerous by design — emptying the trash is a real
thing to want — it was that a single POST destroyed data with no count, no
sample, and nothing to make a wrong call visible.

So the rule here is narrow and deliberate: **destructive bulk operations answer
with a preview and refuse to act without an explicit confirmation.** The preview
is a `GET`, so asking what would happen never changes anything.

An empty result is not a confirmation prompt. "Nothing to delete" should say so
and get out of the way — a dialog offering to delete zero things is how people
learn to click through dialogs.
"""

from __future__ import annotations

import pytest


def _make_note(client, title: str, tags: list[str] | None = None) -> dict:
    """Capture, wait for the pipeline, then tag.

    Two things here are not obvious. Capture is async, so the row comes back
    `pending`. And `tags` passed to `/api/capture/text` are **discarded** —
    `process.py` writes `enriched["tags"]` over whatever you sent, so a note
    captured with `["work"]` comes back tagged from its text. Tagging after the
    pipeline is what the UI and the API both actually do.
    """
    from conftest import wait_done

    r = client.post("/api/capture/text", json={"text": f"body of {title}", "title": title})
    assert r.status_code == 200
    note = wait_done(client, r.json()["id"])
    if tags:
        patched = client.patch(f"/api/notes/{note['id']}", json={"tags": tags})
        assert patched.status_code == 200
        note = patched.json()
    return note


@pytest.fixture()
def trashed(client):
    ids = []
    for title in ("alpha", "bravo", "charlie"):
        n = _make_note(client, title)
        client.delete(f"/api/notes/{n['id']}")
        ids.append(n["id"])
    return ids


# ---- empty trash ----------------------------------------------------------


def test_the_preview_counts_and_samples(client, trashed) -> None:
    body = client.get("/api/trash/empty").json()
    assert body["count"] == 3
    assert len(body["samples"]) >= 1
    # A sample the user can recognise is the whole point. An id is not.
    assert all(s.get("title") for s in body["samples"]), body["samples"]


def test_the_preview_does_not_delete_anything(client, trashed) -> None:
    client.get("/api/trash/empty")
    assert len(client.get("/api/trash").json()) == 3


def test_purging_without_confirming_changes_nothing(client, trashed) -> None:
    """The regression this whole file exists for."""
    r = client.post("/api/trash/empty", json={})
    assert r.status_code == 409
    assert len(client.get("/api/trash").json()) == 3


def test_the_refusal_carries_the_preview_so_the_ui_need_not_call_twice(client, trashed) -> None:
    r = client.post("/api/trash/empty", json={})
    detail = r.json()["detail"]
    assert detail["count"] == 3
    # The prose too, not just the structured field: this string is what someone
    # reads when they curl the endpoint, and "this would affect some items"
    # tells them nothing about whether to press on.
    assert "3" in detail["message"]


def test_confirming_purges(client, trashed) -> None:
    r = client.post("/api/trash/empty", json={"confirm": True})
    assert r.status_code == 200
    assert r.json()["purged"] == 3
    assert client.get("/api/trash").json() == []


def test_emptying_an_empty_trash_is_a_no_op_not_a_prompt(client) -> None:
    """A dialog offering to delete zero things is how people learn to click
    through dialogs."""
    assert client.get("/api/trash/empty").json()["count"] == 0
    assert client.post("/api/trash/empty", json={}).status_code == 200


def test_confirming_on_an_empty_trash_still_succeeds(client) -> None:
    assert client.post("/api/trash/empty", json={"confirm": True}).json()["purged"] == 0


def test_the_sample_count_is_bounded(client, monkeypatch) -> None:
    """A preview that returns 10,000 titles is a payload attack on the dialog."""
    from fleeting.services.bulk import PREVIEW_SAMPLES

    for i in range(12):
        n = _make_note(client, f"note {i}")
        client.delete(f"/api/notes/{n['id']}")
    body = client.get("/api/trash/empty").json()
    assert body["count"] == 12
    assert len(body["samples"]) <= PREVIEW_SAMPLES


# ---- delete a tag everywhere ---------------------------------------------


def test_tag_delete_refuses_without_confirming(client) -> None:
    _make_note(client, "one", tags=["work"])
    r = client.post("/api/tags/delete", json={"tag": "work"})
    assert r.status_code == 409


def test_tag_delete_preview_counts_the_affected_notes(client) -> None:
    for i in range(3):
        _make_note(client, f"n{i}", tags=["work"])
    body = client.get("/api/tags/delete/preview", params={"tag": "work"}).json()
    assert body["count"] == 3
    assert body["tag"] == "work"


def test_tag_delete_preview_does_not_change_the_notes(client) -> None:
    _make_note(client, "one", tags=["work"])
    client.get("/api/tags/delete/preview", params={"tag": "work"})
    # `/api/tags` is a list of tag rows, not a mapping.
    assert [t["tag"] for t in client.get("/api/tags").json() if t["tag"] == "work"]


def test_confirming_tag_delete_still_strips_it(client) -> None:
    _make_note(client, "one", tags=["work"])
    r = client.post("/api/tags/delete", json={"tag": "work", "confirm": True})
    assert r.status_code == 200
    assert r.json()["updated"] == 1


def test_deleting_an_unused_tag_needs_no_confirmation(client) -> None:
    """Same rule as the trash: nothing to lose is nothing to confirm."""
    r = client.post("/api/tags/delete", json={"tag": "never-used"})
    assert r.status_code == 200
    assert r.json()["updated"] == 0


def test_the_two_previews_agree_on_the_number(client, trashed) -> None:
    """A count the UI shows and a count the server enforces being different is
    worse than no count."""
    assert client.get("/api/trash/empty").json()["count"] == len(
        client.get("/api/trash").json()
    )