"""#473 provenance, #475 a context snapshot, #478 live pointers.

The column is the whole design. `source` already holds a JSON blob with the URL,
the channel, the importer and the imported path — and a JSON blob is not
filterable. "Show me everything that came from a YouTube link" has to be
answerable without the caller knowing how `source` is shaped.

The properties that matter:

1. **The value is derived once, by one function.** A second place that decides
   "what counts as a YouTube capture" is a second place that disagrees with the
   first — the same lesson as #459's sensitive flag, which was four separate
   calls that could contradict each other.
2. **#475 snapshots rather than references.** The activity collector keeps
   updating, so a live reference to "the current project" at read time answers a
   question about *now* when the question was about the moment of capture. Six
   weeks later those are different answers.
3. **#478 is a pointer, not a copy.** Duplicating the source's content would make
   a change to the original invisible from the note that came out of it, and a
   derived note that silently diverges from its source is worse than one that
   points at it.
4. **An explicit provenance wins.** A caller that knows better can say so, and a
   filter that ignored an explicit value would be lying about it.
"""

from __future__ import annotations

import pytest

from fleeting.services.provenance import (
    AUDIO,
    FEED,
    FILE,
    MARKDOWN_IMPORT,
    PAGE,
    PDF,
    SOURCES,
    TEXT,
    VAULT,
    VOICE,
    YOUTUBE,
    has_context,
    pointer_for,
    provenance_of,
    snapshot_context,
)


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "pr.db"))
    database.migrate()
    return database


def note(**extra) -> dict:
    return {"id": "n1", "title": "t", "type": "text", "raw_text": "r", "source": {}, **extra}


# ---- the vocabulary --------------------------------------------------------


def test_the_vocabulary_is_closed() -> None:
    """An open set turns into a taxonomy nobody can filter by — "youtube" and
    "YouTube" and "yt" are three filters for one thing."""
    assert len(set(SOURCES)) == len(SOURCES)
    assert SOURCES == (YOUTUBE, VOICE, TEXT, FILE, FEED, PAGE, PDF, AUDIO, MARKDOWN_IMPORT, VAULT)


@pytest.mark.parametrize(
    "given,expected",
    [
        ({"type": "youtube"}, YOUTUBE),
        ({"type": "voice"}, VOICE),
        ({"type": "file"}, FILE),
        ({"type": "text"}, TEXT),
        ({}, TEXT),
        ({"type": "something-new"}, TEXT),
        ({"source": {"imported_from": "markdown-folder"}}, MARKDOWN_IMPORT),
        ({"source": {"imported_from": "rss"}}, FEED),
        ({"source": {"imported_from": "url"}}, PAGE),
        ({"source": {"imported_from": "pdf"}}, PDF),
        ({"source": {"imported_from": "audio"}}, AUDIO),
        ({"source": {"from_vault": True}}, VAULT),
    ],
)
def test_provenance_is_derived_from_the_note(given, expected) -> None:
    assert provenance_of(note(**given)) == expected


def test_a_voice_channel_with_no_url_is_voice() -> None:
    """A channel with no link is a dictated note; one *with* a link is a
    retrieval, and treating them the same loses the distinction."""
    assert provenance_of(note(source={"channel": "phone"})) == VOICE


def test_a_voice_channel_with_a_url_is_not_voice() -> None:
    assert provenance_of(note(source={"channel": "yt", "url": "https://y.com/1"})) == TEXT


def test_a_feed_url_on_an_existing_feed_is_a_feed() -> None:
    assert provenance_of(note(source={"feed": "https://x/f.xml", "url": "https://x/1"})) == FEED


def test_a_malformed_source_does_not_raise() -> None:
    """`source` is a JSON column; a hand-edited row can hold anything."""
    assert provenance_of(note(source="not a dict")) == TEXT
    assert provenance_of(note(source=None)) == TEXT


# ---- #473: stored and filterable -------------------------------------------


def test_provenance_is_stored_on_insert(db) -> None:
    db.insert_note({"id": "a", "title": "v", "type": "youtube", "raw_text": "x"})
    db.commit()
    assert db.get_note("a")["provenance"] == YOUTUBE


def test_an_explicit_provenance_wins(db) -> None:
    """A caller that knows better can say so; a filter that ignored it would be
    lying about it."""
    db.insert_note({"id": "a", "title": "v", "type": "text", "raw_text": "x", "provenance": "custom"})
    db.commit()
    assert db.get_note("a")["provenance"] == "custom"


def test_notes_can_be_filtered_by_provenance(db) -> None:
    db.insert_note({"id": "a", "title": "v", "type": "youtube", "raw_text": "x"})
    db.insert_note({"id": "b", "title": "t", "type": "text", "raw_text": "x"})
    db.commit()
    assert [n["id"] for n in db.list_notes(provenance=YOUTUBE)] == ["a"]


def test_an_unknown_provenance_matches_nothing(db) -> None:
    db.insert_note({"id": "a", "title": "t", "type": "text", "raw_text": "x"})
    db.commit()
    assert db.list_notes(provenance="telepathy") == []


def test_no_filter_still_returns_everything(db) -> None:
    db.insert_note({"id": "a", "title": "v", "type": "youtube", "raw_text": "x"})
    db.insert_note({"id": "b", "title": "t", "type": "text", "raw_text": "x"})
    db.commit()
    assert len(db.list_notes(provenance=None)) == 2


def test_an_empty_filter_matches_nothing(db) -> None:
    """Distinct from *no* filter. `?provenance=` is a question with an empty
    answer, not the absence of one, and treating it as "no filter" would turn a
    typo in a URL into the whole inbox."""
    db.insert_note({"id": "a", "title": "t", "type": "text", "raw_text": "x"})
    db.commit()
    assert db.list_notes(provenance="") == []
    assert len(db.list_notes(provenance=None)) == 1


def test_provenance_and_type_filter_together(db) -> None:
    """A note can be `type: youtube` and `provenance: text`; both filters are
    useful and they are not the same thing."""
    db.insert_note({"id": "a", "title": "v", "type": "youtube", "raw_text": "x"})
    db.insert_note({"id": "b", "title": "v", "type": "youtube", "raw_text": "x", "provenance": "custom"})
    db.commit()
    assert [n["id"] for n in db.list_notes(note_type="youtube", provenance="custom")] == ["b"]


# ---- #475: a snapshot, not a reference --------------------------------------


def test_context_is_snapshotted() -> None:
    snap = snapshot_context({"project": "fleeting", "branch": "main", "app": "code"})
    assert snap["project"] == "fleeting"
    assert snap["branch"] == "main"


def test_missing_context_is_empty_rather_than_absent() -> None:
    """A note with `project: ""` is honest; a missing key is indistinguishable
    from 'we forgot to record it'."""
    assert snapshot_context(None) == {"project": "", "branch": "", "workspace": "", "app": ""}


def test_a_snapshot_does_not_follow_the_activity_row() -> None:
    """A live reference to 'the current project' answers a question about *now*
    when the question was about the moment of capture."""
    activity = {"project": "fleeting", "branch": "main"}
    snap = snapshot_context(activity)
    activity["project"] = "something-else"
    assert snap["project"] == "fleeting"


def test_an_empty_snapshot_is_recognised_as_nothing_worth_showing() -> None:
    """Four empty strings in every note's frontmatter is noise."""
    assert has_context(snapshot_context(None)) is False
    assert has_context(snapshot_context({"project": "x"})) is True
    assert has_context(None) is False


# ---- #478: a pointer, not a copy -------------------------------------------


def test_a_url_becomes_a_pointer() -> None:
    p = pointer_for(note(source={"url": "https://example.com/a/very/long/path"}))
    assert p["kind"] == "url"
    assert "example.com" in p["label"]


def test_an_imported_file_becomes_a_pointer() -> None:
    p = pointer_for(note(source={"imported_path": "sub/one.md"}))
    assert p["kind"] == "file"
    assert p["label"] == "one.md"


def test_a_feed_pointer_is_last() -> None:
    assert pointer_for(note(source={"feed": "https://x/f.xml"}))["kind"] == "feed"


def test_a_captured_note_has_no_pointer() -> None:
    """Nothing to point at is not a pointer to nothing."""
    assert pointer_for(note()) is None


def test_a_pointer_does_not_copy_the_source_content() -> None:
    """Duplicating it would make a change to the original invisible from here."""
    p = pointer_for(note(source={"url": "https://x/1"}))
    assert set(p) == {"kind", "label", "target"}
    assert "content" not in p and "body" not in p


def test_a_malformed_source_gives_no_pointer() -> None:
    assert pointer_for(note(source="not a dict")) is None


# ---- the endpoints ---------------------------------------------------------


def test_notes_can_be_filtered_through_the_api(client) -> None:
    """Inserted rather than captured: the YouTube *pipeline* downloads a video,
    and this is a test of the filter, not of yt-dlp."""
    st = client.app.state.st
    st.db.insert_note({"id": "vid", "title": "v", "type": "youtube", "raw_text": "x"})
    st.db.insert_note({"id": "txt", "title": "t", "type": "text", "raw_text": "x"})
    st.db.commit()
    assert [n["id"] for n in client.get("/api/notes?provenance=youtube").json()] == ["vid"]
    assert len(client.get("/api/notes?provenance=text").json()) == 1


def test_an_unknown_provenance_returns_nothing_through_the_api(client) -> None:
    assert client.get("/api/notes?provenance=telepathy").json() == []


def test_the_provenance_summary_endpoint(client) -> None:
    body = client.get("/api/vault/provenance").json()
    assert set(body["counts"]) >= {YOUTUBE, TEXT, VOICE}
    assert body["total"] >= 0
    assert "provenance=" in body["filter"]