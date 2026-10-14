"""#138: retention policies per capture source.

Three decisions are under test, and the middle one is the one that matters:

1. **Only the sources you name.** There is no catch-all. A policy that quietly
   applied to everything would age out the notes you wrote in favour of the ones
   you were dictated — the exact inverse of what the feature is for.
2. **Retention trashes; it does not delete.** Moving to the trash is the
   recoverable step, and `trash_retention_days` is what turns it permanent. A
   retention policy that hard-deleted would be a slow-motion version of the panic
   button: data gone on a timer you set once and forgot, with no window in which
   to notice. So the test asserts the note is still readable after a prune.
3. **A typo is visible, not fatal.** Malformed entries are dropped so a bad
   config cannot stop the app starting, and `ignored` reports them — a policy
   that quietly does nothing is indistinguishable from one that is working.

The timestamp handling is also worth stating: `created_at` is UTC while "a week
old" is a local judgement, so cutoffs are computed in UTC and the boundary is
tested on both sides of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fleeting.services.retention import (
    MAX_DAYS,
    MIN_DAYS,
    describe_policies,
    due_notes,
    parse_policies,
    preview_due,
    prune,
)


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "r.db"))
    database.migrate()
    return database


def add(db, note_id: str, type_: str, age_days: float) -> str:
    """A note created `age_days` ago, in UTC like every `created_at`."""
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.insert_note(
        {"id": note_id, "title": note_id, "raw_text": "body", "type": type_, "created_at": created.isoformat(timespec="seconds")}
    )
    db.commit()
    return created.isoformat(timespec="seconds")


# ---- parsing ---------------------------------------------------------------


def test_a_simple_policy_parses() -> None:
    assert parse_policies("youtube:7") == {"youtube": 7}


def test_several_policies_parse() -> None:
    assert parse_policies("youtube:7, file:30") == {"youtube": 7, "file": 30}


def test_nothing_configured_is_no_policies() -> None:
    assert parse_policies("") == {}


@pytest.mark.parametrize(
    "spec",
    ["youtube", "youtube:", "youtube:abc", ":7", "youtube:0", "youtube:-3"],
)
def test_malformed_entries_are_dropped_not_fatal(spec: str) -> None:
    """A typo in a config file must not stop the app starting."""
    assert parse_policies(spec) == {}


def test_one_bad_entry_does_not_lose_the_good_ones() -> None:
    assert parse_policies("youtube:7, nonsense, file:30") == {"youtube": 7, "file": 30}


def test_a_policy_below_a_day_is_refused() -> None:
    """Fires on the next poll and deletes faster than a person could notice."""
    assert parse_policies(f"youtube:{MIN_DAYS - 1}") == {}


def test_a_policy_is_capped() -> None:
    assert parse_policies("youtube:99999") == {"youtube": MAX_DAYS}


def test_the_last_policy_for_a_source_wins() -> None:
    assert parse_policies("youtube:7, youtube:30") == {"youtube": 30}


# ---- what is due -----------------------------------------------------------


def test_nothing_is_due_without_policies(db) -> None:
    add(db, "old", "youtube", 400)
    assert due_notes(db, {}) == []


def test_only_the_named_source_ages_out(db) -> None:
    """The property the item is for. A catch-all would age out the notes you
    wrote in favour of the ones you were dictated."""
    add(db, "vid", "youtube", 10)
    add(db, "note", "text", 10)
    due = [r["id"] for r in due_notes(db, {"youtube": 7})]
    assert due == ["vid"]


def test_a_recent_note_of_the_named_source_is_kept(db) -> None:
    add(db, "vid", "youtube", 2)
    assert due_notes(db, {"youtube": 7}) == []


def test_several_sources_are_collected_together(db) -> None:
    add(db, "vid", "youtube", 10)
    add(db, "doc", "file", 40)
    ids = {r["id"] for r in due_notes(db, {"youtube": 7, "file": 30})}
    assert ids == {"vid", "doc"}


def test_results_are_oldest_first(db) -> None:
    add(db, "newer", "youtube", 10)
    add(db, "older", "youtube", 30)
    assert [r["id"] for r in due_notes(db, {"youtube": 7})] == ["older", "newer"]


def test_a_note_already_in_the_trash_is_not_due_again(db) -> None:
    add(db, "vid", "youtube", 10)
    prune(db, "youtube:7", confirm=True)
    assert due_notes(db, {"youtube": 7}) == []


# ---- the recoverable window ------------------------------------------------


def test_pruning_trashes_rather_than_deletes(db) -> None:
    """A retention policy that hard-deleted would be a slow-motion panic button."""
    add(db, "vid", "youtube", 10)
    prune(db, "youtube:7", confirm=True)
    note = db.get_note("vid")
    assert note is not None
    assert note["trashed_at"] is not None


def test_a_trashed_note_can_still_be_recovered(db) -> None:
    add(db, "vid", "youtube", 10)
    prune(db, "youtube:7", confirm=True)
    db.execute("UPDATE notes SET trashed_at = NULL WHERE id = 'vid'")
    db.commit()
    assert db.get_note("vid")["trashed_at"] is None


def test_the_preview_says_the_step_is_recoverable(db) -> None:
    add(db, "vid", "youtube", 10)
    assert preview_due(db, {"youtube": 7})["recoverable"] is True


def test_the_preview_names_the_notes_not_just_counts(db) -> None:
    """You cannot confirm 'delete 4 rows'."""
    add(db, "vid", "youtube", 10)
    assert preview_due(db, {"youtube": 7})["samples"][0]["title"] == "vid"


# ---- confirmation ----------------------------------------------------------


def test_an_unconfirmed_prune_is_refused(db) -> None:
    """With something due. An empty room has nothing to confirm."""
    from fastapi import HTTPException

    add(db, "vid", "youtube", 10)
    with pytest.raises(HTTPException) as err:
        prune(db, "youtube:7", confirm=False)
    assert err.value.status_code == 409
    assert db.get_note("vid")["trashed_at"] is None


def test_nothing_due_succeeds_without_asking(client) -> None:
    """A dialog offering to delete nothing is how people learn to click through
    dialogs."""
    assert prune(client.app.state.st.db, "youtube:7", confirm=False)["trashed"] == 0


# ---- describing ------------------------------------------------------------


def test_a_typo_is_reported_rather_than_swallowed() -> None:
    """A policy that quietly does nothing is indistinguishable from one that is
    working."""
    described = describe_policies("youtube:7, nonsense")
    assert described["policies"] == {"youtube": 7}
    assert described["ignored"] == ["nonsense"]


def test_describing_nothing_still_explains_itself() -> None:
    assert "nothing is aged out" in describe_policies("")["explains"]


def test_describing_a_policy_says_it_is_recoverable() -> None:
    assert "trash" in describe_policies("youtube:7")["explains"]


# ---- the endpoints ---------------------------------------------------------


def test_the_status_endpoint_reports_the_due_count(client) -> None:
    client.put("/api/settings", json={"notes_retention_by_source": "youtube:7"})
    body = client.get("/api/retention").json()
    assert body["policies"] == {"youtube": 7}
    assert body["due"]["count"] == 0


def test_pruning_through_the_api_trashes(client) -> None:
    """End to end, with a genuinely old note so there is something to age out."""
    add(client.app.state.st.db, "vid", "youtube", 30)
    r = client.post("/api/retention/prune", json={"policies": "youtube:7", "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["trashed"] == 1
    assert client.app.state.st.db.get_note("vid")["trashed_at"] is not None


def test_pruning_without_confirm_is_refused_through_the_api(client) -> None:
    add(client.app.state.st.db, "vid", "youtube", 30)
    r = client.post("/api/retention/prune", json={"policies": "youtube:7"})
    assert r.status_code == 409
    assert client.app.state.st.db.get_note("vid")["trashed_at"] is None


def test_pruning_nothing_due_succeeds_without_asking(client) -> None:
    """A dialog offering to delete nothing is how people learn to click through
    dialogs."""
    r = client.post("/api/retention/prune", json={"policies": "youtube:7"})
    assert r.status_code == 200
    assert r.json()["trashed"] == 0


def test_the_default_is_no_policies() -> None:
    """Asserted separately: a correct `parse_policies` with a non-empty shipped
    default is still the bug."""
    from fleeting.config import Config

    assert Config().notes.retention_by_source == ""
