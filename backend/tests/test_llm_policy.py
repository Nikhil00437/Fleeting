"""#459: per-source "never use for AI".

There is already a per-note switch — `notes.sensitive`, #26 — which routes a
single capture past every model. This is the same promise made once, by source
kind, for every capture of that kind: a YouTube link pasted by reflex, a voice
memo of something a colleague said, a screenshot of a document you were not
meant to keep.

Configuration rather than inference, because the whole point is that you decide.
A heuristic guess at "this looks private" is the wrong default in both
directions: it misses the source you forgot about, and it marks things you did
not mean to hide.

**The guarantee is "no model sees it", not "enrichment is skipped".** A blocked
note is enriched by heuristics exactly as a `sensitive` note is, because a note
with no tags and no summary is a note you will not recognise in your own inbox.
The difference is that nothing leaves the machine, including the embedding index
— which is a second, quieter route to the same text and the one that would
otherwise defeat the switch.
"""

from __future__ import annotations

from conftest import wait_done
from fleeting.config import Config
from fleeting.services.llm_policy import blocked_types


def cfg_with(*types: str) -> Config:
    cfg = Config()
    cfg.llm.never_use_ai_types = ", ".join(types)
    return cfg


# ---- the configuration ----------------------------------------------------


def test_nothing_is_blocked_by_default() -> None:
    """Opt-in. A default that blocked a capture kind would surprise everyone."""
    assert blocked_types(Config()) == []


def test_a_configured_type_is_blocked() -> None:
    assert blocked_types(cfg_with("youtube")) == ["youtube"]


def test_the_list_is_normalised() -> None:
    """Hand-edited TOML arrives with spaces, case and stray hashes."""
    assert blocked_types(cfg_with(" YouTube , VOICE ,, ")) == ["youtube", "voice"]


def test_duplicates_collapse() -> None:
    assert blocked_types(cfg_with("youtube", "youtube")) == ["youtube"]


def test_a_blank_entry_is_not_a_block_on_the_empty_type() -> None:
    """`" , , "` would otherwise block notes whose type is falsy."""
    assert blocked_types(cfg_with(" , ")) == []


# ---- the policy -----------------------------------------------------------


def test_a_blocked_type_is_a_blocked_type() -> None:
    assert "youtube" in blocked_types(cfg_with("youtube"))


def test_an_unlisted_type_is_not_blocked() -> None:
    assert "text" not in blocked_types(cfg_with("youtube"))


def test_a_note_type_is_compared_case_insensitively() -> None:
    assert "youtube" in blocked_types(cfg_with("YouTube"))

# ---- the pipeline ---------------------------------------------------------


def _capture_as(client, kind: str, title: str) -> dict:
    """Insert a capture of a given `type` and let the pipeline run it.

    The row is written directly rather than captured and then retyped: the text
    route always sets `type: text`, and flipping it afterwards means processing
    the note twice, which is a race between `wait_done` and the second pass.
    Under test is the pipeline's decision, not how the type got there.
    """
    st = client.app.state.st
    note = st.db.insert_note(
        {
            "title": title,
            "raw_text": f"body of {title}",
            "type": kind,
            "status": "pending",
        }
    )
    st.processor.enqueue(note["id"])
    return wait_done(client, note["id"])


def _embedding_deletions(client, monkeypatch) -> list[str]:
    """Note ids the pipeline had its embedding removed for.

    Watching the *decision* rather than the artifact, because this fixture runs
    with no embedding provider: asserting "no embedding exists" passes whether
    the block works or the fixture simply never embeds anything. That is the
    vacuous test this started as.
    """
    calls: list[str] = []
    db = client.app.state.st.db
    original = db.delete_note_embedding

    def spy(note_id, *a, **k):
        calls.append(note_id)
        return original(note_id, *a, **k)

    monkeypatch.setattr(db, "delete_note_embedding", spy)
    return calls


def test_a_blocked_type_is_enriched_without_a_model(client) -> None:
    client.put("/api/settings", json={"llm_never_use_ai_types": "youtube"})
    note = _capture_as(client, "youtube", "a talk I did not consent to sending")
    assert note["source"].get("enrichment") == "heuristic-source-blocked"


def test_an_unblocked_type_is_not_labelled_blocked(client) -> None:
    note = _capture_as(client, "voice", "an ordinary memo")
    assert note["source"].get("enrichment") != "heuristic-source-blocked"


def test_a_blocked_note_is_still_enriched(client) -> None:
    """Heuristics, not nothing. A note with no tags and no summary is one you
    will not recognise in your own inbox — and *that* is the data leak."""
    client.put("/api/settings", json={"llm_never_use_ai_types": "youtube"})
    note = _capture_as(client, "youtube", "still needs to be findable")
    assert note["title"]
    assert note["review_state"] in ("raw", "enriched")


def test_a_blocked_note_has_its_embedding_removed(client, monkeypatch) -> None:
    """The quieter route to the same text. Without this the switch is defeated
    by the vector index, which may be a remote provider — and a vector written
    before the switch was turned on would keep the note findable either way."""
    calls = _embedding_deletions(client, monkeypatch)
    client.put("/api/settings", json={"llm_never_use_ai_types": "youtube"})
    note = _capture_as(client, "youtube", "must not become a vector")
    assert note["id"] in calls


def test_an_unblocked_note_keeps_its_embedding(client, monkeypatch) -> None:
    """The negative control. Without it the test above passes in a fixture where
    nothing ever embeds anything."""
    calls = _embedding_deletions(client, monkeypatch)
    note = _capture_as(client, "text", "ordinary capture")
    assert note["id"] not in calls


def test_blocking_a_type_does_not_touch_earlier_notes(client) -> None:
    """Turning the switch on is not retroactive. Re-enrichment applies to
    whatever is reprocessed, and nothing else is touched."""
    note = _capture_as(client, "youtube", "captured before the switch")
    db = client.app.state.st.db
    before = db.get_note(note["id"])
    client.put("/api/settings", json={"llm_never_use_ai_types": "youtube"})
    assert db.get_note(note["id"])["updated_at"] == before["updated_at"]


# ---- gaps found by the first mutation pass -------------------------------


def test_a_note_type_is_matched_case_insensitively(client) -> None:
    """The config side was tested and the *note* side was not, so removing
    `.lower()` from the comparison passed everything."""
    client.put("/api/settings", json={"llm_never_use_ai_types": "youtube"})
    note = _capture_as(client, "YouTube", "mixed case type")
    assert note["source"].get("enrichment") == "heuristic-source-blocked"


def test_a_blocked_note_does_not_get_the_preferred_vocabulary(client) -> None:
    """#257 skips the vocabulary for a `sensitive` note because those tags come
    from keywords, and rewriting them would misdescribe where they came from.
    Exactly the same reasoning applies here — and it never ran in this suite at
    all, because the vocabulary was empty in every test."""
    client.put(
        "/api/settings",
        json={"llm_preferred_tags": "inbox, idea", "llm_never_use_ai_types": "youtube"},
    )
    note = _capture_as(client, "youtube", "a talk about routers and switches")
    tags = [t.lower() for t in (note.get("tags") or [])]
    assert "inbox" not in tags, tags
    assert "idea" not in tags, tags


def test_an_unblocked_note_does_apply_the_preferred_vocabulary(client, monkeypatch) -> None:
    """The control, so the test above is not passing because the vocabulary
    stopped working at all.

    Asserted by watching whether the vocabulary is *consulted*, not by looking at
    the tags: `apply_preferred_tags` snaps a model tag onto a near-miss
    vocabulary term, it does not add terms, so whether a given note ends up
    carrying "inbox" depends on what the heuristic happened to produce.
    """
    import fleeting.process as process_module

    calls: list[int] = []
    original = process_module.apply_preferred_tags

    def spy(tags, vocabulary):
        calls.append(len(tags))
        return original(tags, vocabulary)

    monkeypatch.setattr(process_module, "apply_preferred_tags", spy)

    client.put("/api/settings", json={"llm_preferred_tags": "inbox, idea"})
    _capture_as(client, "text", "an ordinary capture about routers")
    assert calls, "the vocabulary was never applied to an ordinary note"


def test_a_blocked_note_never_consults_the_preferred_vocabulary(client, monkeypatch) -> None:
    """#257 skips the vocabulary for a `sensitive` note because those tags came
    from keywords, and rewriting them would misdescribe where they came from.
    The same reasoning applies here — and this branch never ran in the suite at
    all, because the vocabulary was empty in every test."""
    import fleeting.process as process_module

    calls: list[int] = []
    original = process_module.apply_preferred_tags
    monkeypatch.setattr(
        process_module, "apply_preferred_tags", lambda t, v: (calls.append(1), original(t, v))[1]
    )

    client.put(
        "/api/settings",
        json={"llm_preferred_tags": "inbox, idea", "llm_never_use_ai_types": "youtube"},
    )
    _capture_as(client, "youtube", "a talk about routers and switches")
    assert not calls, "the vocabulary was applied to a blocked note"
