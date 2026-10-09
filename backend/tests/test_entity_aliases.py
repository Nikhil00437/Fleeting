"""#414 alias merging, #417 same-first-name disambiguation.

The heuristic cannot know that "Ben C." and "Ben" are one person, and it
should not guess: silently merging two real people corrupts the index in a
way that is invisible afterwards. So the user states the alias and the
merge is deterministic; #417 surfaces the collision rather than resolving
it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.entities import (
    ambiguous_first_names,
    people_index,
    resolve_ambiguity,
)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.migrate()
    return database


def _say(db: Database, text: str, day: str = "2026-05-01") -> None:
    db.insert_note({
        "title": "n", "raw_text": text, "type": "text",
        "created_at": f"{day}T09:00:00+00:00",
    })


# ---- #414 alias merging --------------------------------------------------


def test_without_an_alias_the_index_is_unchanged(db: Database) -> None:
    _say(db, "Ben called.")
    _say(db, "Ben C. called.")
    assert {p["name"] for p in people_index(db)} == {"Ben", "Ben C."}


def test_an_alias_collapses_two_rows_into_one(db: Database) -> None:
    _say(db, "Ben called.")
    _say(db, "Ben C. called.")
    db.record_entity_alias("Ben C.", "Ben")
    assert [p["name"] for p in people_index(db)] == ["Ben"]


def test_a_merged_row_sums_the_mentions(db: Database) -> None:
    _say(db, "Ben called. Ben again.")
    _say(db, "Ben C. called.")
    db.record_entity_alias("Ben C.", "Ben")
    assert people_index(db)[0]["mentions"] == 3


def test_a_merged_row_spans_both_date_ranges(db: Database) -> None:
    _say(db, "Ben called.", day="2026-01-01")
    _say(db, "Ben C. called.", day="2026-09-01")
    db.record_entity_alias("Ben C.", "Ben")
    entry = people_index(db)[0]
    assert entry["first_seen"] == "2026-01-01"
    assert entry["last_seen"] == "2026-09-01"


def test_an_alias_is_case_insensitive(db: Database) -> None:
    _say(db, "ben called.")
    _say(db, "Ben C. called.")
    db.record_entity_alias("ben c.", "Ben")
    assert [p["name"] for p in people_index(db)] == ["Ben"]


def test_aliases_do_not_chain_into_a_cycle(db: Database) -> None:
    """Ben C. -> Ben and Ben -> Ben Both must not fold forever."""
    _say(db, "Ben Both called.")
    db.record_entity_alias("Ben C.", "Ben")
    db.record_entity_alias("Ben", "Ben Both")
    names = {p["name"] for p in people_index(db)}
    assert "Ben Both" in names
    assert len(names) == 1


def test_an_alias_to_itself_is_rejected(db: Database) -> None:
    _say(db, "Ben called.")
    assert db.record_entity_alias("Ben", "Ben") is False


def test_listing_aliases_returns_what_the_user_stated(db: Database) -> None:
    db.record_entity_alias("Ben C.", "Ben")
    assert db.list_entity_aliases() == [{"alias": "Ben C.", "canonical": "Ben"}]


def test_deleting_an_alias_restores_both_rows(db: Database) -> None:
    _say(db, "Ben called.")
    _say(db, "Ben C. called.")
    db.record_entity_alias("Ben C.", "Ben")
    assert len(people_index(db)) == 1
    db.delete_entity_alias("Ben C.")
    assert len(people_index(db)) == 2


def test_notes_for_a_canonical_name_include_its_aliases(db: Database) -> None:
    from fleeting.services.entities import notes_for_person

    _say(db, "Ben called about pricing.")
    _say(db, "Ben C. called about the contract.")
    db.record_entity_alias("Ben C.", "Ben")
    assert len(notes_for_person(db, "Ben")) == 2


def test_sensitive_notes_stay_out_of_a_merge(db: Database) -> None:
    _say(db, "Ben called.")
    db.insert_note({
        "title": "s", "raw_text": "Ben C. password is x.", "type": "text",
        "sensitive": 1,
    })
    db.record_entity_alias("Ben C.", "Ben")
    assert people_index(db)[0]["mentions"] == 1


# ---- #417 ambiguity ------------------------------------------------------


def test_one_ben_is_not_ambiguous(db: Database) -> None:
    _say(db, "Ben called.")
    assert ambiguous_first_names(db) == []


def test_two_bens_are_flagged(db: Database) -> None:
    """Distinct spellings of the same first name, not two mentions of one."""
    _say(db, "Ben called about pricing.")
    _say(db, "Ben Whitaker called about the contract.")
    assert [a["first_name"] for a in ambiguous_first_names(db)] == ["Ben"]


def test_two_mentions_of_one_ben_are_not_ambiguous(db: Database) -> None:
    _say(db, "Ben called about pricing.")
    _say(db, "Ben called about the contract.")
    assert ambiguous_first_names(db) == []


def test_ambiguity_lists_the_full_names_involved(db: Database) -> None:
    _say(db, "Ben called.")
    db.insert_note({
        "title": "n", "raw_text": "Ben Whitaker called.", "type": "text",
    })
    amb = ambiguous_first_names(db)[0]
    assert sorted(amb["names"]) == ["Ben", "Ben Whitaker"]


def test_merging_the_ambiguity_clears_it(db: Database) -> None:
    _say(db, "Ben called.")
    db.insert_note({"title": "n", "raw_text": "Ben Whitaker called.", "type": "text"})
    assert ambiguous_first_names(db)

    assert resolve_ambiguity(db, "Ben Whitaker", "Ben") is True
    assert ambiguous_first_names(db) == []


def test_resolving_toward_an_unknown_name_is_refused(db: Database) -> None:
    _say(db, "Ben called.")
    db.insert_note({"title": "n", "raw_text": "Ben Whitaker called.", "type": "text"})
    assert resolve_ambiguity(db, "Ben Whitaker", "Nobody") is False


def test_an_initial_and_a_full_name_are_two_people_until_told(db: Database) -> None:
    """The bug this cluster exists to fix: 'Ben C.' is not 'Ben'."""
    _say(db, "Ben called.")
    _say(db, "Ben C. called.")
    assert {p["name"] for p in people_index(db)} == {"Ben", "Ben C."}
    assert [a["names"] for a in ambiguous_first_names(db)] == [["Ben", "Ben C."]]
