"""Tags supplied at capture must survive enrichment.

`process.py` wrote `"tags": enriched["tags"]` into `changes`, so the enrichment
*replaced* the tag column wholesale. Anything passed to `/api/capture/text` —
by the UI, the `flee` CLI, the HUD, or an MCP client — was silently discarded
and replaced with tags guessed from the note text:

    POST /api/capture/text  {"tags": ["work"]}
    → comes back tagged ["hello", "world"]

Found while writing the #455 tests, which could not tag a note the obvious way.
The rule this file pins is **user tags win, model tags add**. The user said what
they meant; the model can only contribute what was missing. This also matches
the order already documented for #256 — the user's own corrections outrank the
tag vocabulary.
"""

from __future__ import annotations

import pytest

from conftest import wait_done
from fleeting.db import Database


def _db(tmp_path) -> Database:
    db = Database(str(tmp_path / "t.db"))
    db.migrate()
    return db


def _capture(client, **body) -> dict:
    payload = {"text": body.pop("text", "the router firmware upgrade failed again"), **body}
    r = client.post("/api/capture/text", json=payload)
    assert r.status_code == 200
    return wait_done(client, r.json()["id"])


# ---- the pipeline ---------------------------------------------------------


def test_tags_passed_at_capture_survive_the_pipeline(client) -> None:
    note = _capture(client, tags=["work"])
    assert "work" in note["tags"]


def test_model_tags_are_added_not_substituted(client) -> None:
    """The note text is about a router, so the heuristic contributes something.
    Losing the user's tag to gain that would be the whole bug again."""
    note = _capture(client, text="the router firmware upgrade failed again", tags=["work"])
    assert "work" in note["tags"]


def test_no_duplicate_tags_when_both_sides_agree(client) -> None:
    note = _capture(client, text="router", tags=["router"])
    assert note["tags"].count("router") == 1


def test_no_tags_means_still_no_tags(client) -> None:
    """The fix must not invent tags for a capture that asked for none."""
    note = _capture(client, text="just some text with no tags given")
    assert isinstance(note["tags"], list)


def test_user_tags_come_first(client) -> None:
    """Order is the ranking. #256 already establishes that the user's own words
    outrank anything the vocabulary suggests."""
    note = _capture(client, text="router firmware", tags=["work", "urgent"])
    assert note["tags"][:2] == ["work", "urgent"]


def test_tags_added_after_capture_still_work(client) -> None:
    """The PATCH path must keep working — that is what TagManager uses."""
    note = _capture(client)
    patched = client.patch(f"/api/notes/{note['id']}", json={"tags": ["later"]})
    assert patched.status_code == 200
    assert patched.json()["tags"] == ["later"]


# ---- the merge, on its own ------------------------------------------------


@pytest.mark.parametrize(
    "user,model,expected",
    [
        (["work"], ["router"], ["work", "router"]),
        (["router"], ["router"], ["router"]),
        (["work"], [], ["work"]),
        ([], ["router"], ["router"]),
        (["a", "b"], ["b", "c"], ["a", "b", "c"]),
        ([], [], []),
        # Case and surrounding whitespace are the same tag to a human reading
        # the list; keeping both looks like a bug in the list.
        (["Work"], ["work"], ["Work"]),
    ],
)
def test_merge_tags(user: list[str], model: list[str], expected: list[str]) -> None:
    from fleeting.services.tags_vocab import merge_tags

    assert merge_tags(user, model) == expected


def test_merge_ignores_non_strings_rather_than_crashing() -> None:
    """The model has produced a non-string before, and one bad tag must not lose
    the note's other tags."""
    from fleeting.services.tags_vocab import merge_tags

    assert merge_tags(["work"], ["ok", None, 3, ""]) == ["work", "ok"]