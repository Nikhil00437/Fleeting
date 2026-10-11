"""#415 a local birthday and anniversary reminder list.

Dates are the one thing a note mentions that the note itself cannot hold: a
birthday written down in March is still true in November. So these are
extracted once into their own table, where the user can look at them, correct
one, or delete it — and never re-derived, because a reminder that changes
itself is not a reminder.

Extraction is deterministic and narrow. A model asked to find birthdays
invents them — "we should catch up soon" becomes someone's birthday often
enough to be embarrassing — and a wrong reminder is worse than a missed one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.reminders import (
    delete_reminder,
    extract_and_store,
    extract_reminders,
    list_reminders,
    next_occurrence,
    parse_month_day,
    update_reminder,
    upcoming,
)


def _add(db: "Database", name: str, kind: str, month: int, day: int) -> None:
    db.add_reminder(
        name=name,
        kind=kind,
        month=month,
        day=day,
        source_key=f"{name.lower()}|{kind}|{month}-{day}",
    )


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "reminders.db"))
    database.migrate()
    return database


def _note(text: str) -> str:
    return text


# ---- reading a date out of a sentence ------------------------------------


def test_a_month_and_day_parses() -> None:
    assert parse_month_day("March 3") == (3, 3)
    assert parse_month_day("3 March") == (3, 3)
    assert parse_month_day("12 May") == (5, 12)
    assert parse_month_day("december 25") == (12, 25)


def test_a_written_out_month_parses() -> None:
    assert parse_month_day("the 14th of February") == (2, 14)


def test_nonsense_is_not_a_date() -> None:
    assert parse_month_day("sometime") is None
    assert parse_month_day("month 40 day 2") is None
    assert parse_month_day("Marchtember 3") is None


def test_an_impossible_day_is_rejected() -> None:
    """Feb 30 must not become Mar 2 or crash a reminder."""
    assert parse_month_day("February 30") is None


# ---- which day it comes round again ---------------------------------------


def test_a_future_date_this_year() -> None:
    assert next_occurrence((3, 3), today="2026-10-11") == "2027-03-03"


def test_a_past_date_rolls_to_next_year() -> None:
    assert next_occurrence((1, 5), today="2026-10-11") == "2027-01-05"


def test_todays_date_does_not_fire_twice() -> None:
    """A birthday today is today, not next year."""
    assert next_occurrence((10, 11), today="2026-10-11") == "2026-10-11"


def test_a_leap_day_still_lands() -> None:
    """Feb 29 is the one date that does not exist most years."""
    assert next_occurrence((2, 29), today="2026-10-11") == "2027-02-28"


# ---- pulling them out of notes --------------------------------------------


def test_a_birthday_sentence_is_extracted() -> None:
    found = extract_reminders(_note("Priya's birthday is on March 3, don't forget it"))
    assert len(found) == 1
    assert found[0]["name"] == "Priya"
    assert found[0]["kind"] == "birthday"
    assert (found[0]["month"], found[0]["day"]) == (3, 3)


def test_an_anniversary_is_extracted() -> None:
    found = extract_reminders(_note("our anniversary is on 12 May"))
    assert found[0]["kind"] == "anniversary"


def test_a_person_who_is_not_the_subject_is_not_mistaken_for_one() -> None:
    """'her birthday' with no name must not be attributed to anyone."""
    found = extract_reminders(_note("her birthday is on March 3"))
    assert found == [] or found[0]["name"] == ""


def test_a_mention_without_a_date_is_ignored() -> None:
    """Mentioning a birthday is not a reminder until a date is given."""
    assert extract_reminders(_note("Priya's birthday is coming up soon")) == []


def test_two_reminders_in_one_note_are_both_found() -> None:
    found = extract_reminders(
        _note("Priya's birthday is March 3 and our anniversary is on 12 May")
    )
    assert len(found) == 2


def test_prose_about_birthdays_is_not_extracted() -> None:
    """A note *about* birthdays must not create reminders for everyone in it."""
    assert extract_reminders(_note("I hate planning birthday parties for adults")) == []


# ---- the stored list ------------------------------------------------------


def test_an_extracted_reminder_is_stored_once(db: Database) -> None:
    added = extract_and_store(
        db, _note("Priya's birthday is on March 3, don't forget it")
    )
    assert added == 1
    # Same sentence again must not double the list.
    assert extract_and_store(db, _note("Priya's birthday is on March 3")) == 0
    assert len(list_reminders(db)) == 1


def test_a_stored_reminder_can_be_corrected(db: Database) -> None:
    extract_and_store(db, _note("Priya's birthday is on March 3"))
    row = list_reminders(db)[0]
    update_reminder(db, row["id"], {"day": 5})
    assert list_reminders(db)[0]["day"] == 5


def test_a_reminder_can_be_deleted(db: Database) -> None:
    extract_and_store(db, _note("Priya's birthday is on March 3"))
    delete_reminder(db, list_reminders(db)[0]["id"])
    assert list_reminders(db) == []


def test_a_deleted_reminder_is_not_re_added_by_a_reprocess(db: Database) -> None:
    """Deleting is a decision; a reprocess must not undo it."""
    extract_and_store(db, _note("Priya's birthday is on March 3"))
    delete_reminder(db, list_reminders(db)[0]["id"])
    assert extract_and_store(db, _note("Priya's birthday is on March 3")) == 0
    assert list_reminders(db) == []


def test_a_reminder_keeps_the_note_it_came_from(db: Database) -> None:
    """So the list can show why it believes this."""
    note_id = db.insert_note(
        {"title": "t", "raw_text": "Priya's birthday is on March 3", "status": "done"}
    )["id"]
    extract_and_store(db, _note("Priya's birthday is on March 3"), note_id=note_id)
    assert list_reminders(db)[0]["note_id"] == note_id


# ---- what the list shows --------------------------------------------------


def test_upcoming_is_ordered_by_how_soon(db: Database) -> None:
    _add(db, "far", "birthday", 6, 1)
    _add(db, "soon", "birthday", 10, 20)
    _add(db, "later", "birthday", 11, 1)

    rows = upcoming(db, today="2026-10-11", days=90)

    # June is genuinely outside a 90-day window from October -- it comes round
    # again in 2027 -- so "far" belongs with "soon" and "later", not here.
    assert [r["name"] for r in rows] == ["soon", "later"]


def test_a_date_beyond_the_window_rolls_into_next_year(db: Database) -> None:
    _add(db, "far", "birthday", 6, 1)
    assert upcoming(db, today="2026-10-11", days=300)[0]["date"] == "2027-06-01"


def test_upcoming_excludes_what_is_beyond_the_window(db: Database) -> None:
    _add(db, "soon", "birthday", 10, 20)
    _add(db, "far", "birthday", 12, 1)
    assert [r["name"] for r in upcoming(db, today="2026-10-11", days=30)] == ["soon"]


def test_upcoming_counts_the_days_left(db: Database) -> None:
    _add(db, "soon", "birthday", 10, 20)
    row = upcoming(db, today="2026-10-11", days=30)[0]
    assert row["days_until"] == 9


def test_an_empty_list_is_empty_not_an_error(db: Database) -> None:
    assert upcoming(db, today="2026-10-11") == []


def test_todays_reminder_is_first(db: Database) -> None:
    _add(db, "today", "birthday", 10, 11)
    _add(db, "later", "birthday", 11, 1)
    assert upcoming(db, today="2026-10-11", days=30)[0]["name"] == "today"

def test_a_pronoun_is_never_taken_for_a_name(db: Database) -> None:
    """The capitalisation rule is the only thing separating the two.

    A global re.IGNORECASE made '[A-Z]' match lowercase and turned "her" into
    a person with a birthday.
    """
    assert extract_reminders("her birthday is on March 3") == []
    assert extract_reminders("his anniversary is 12 May") == []
    assert extract_reminders("their birthday is March 3") == []


def test_an_anniversary_can_belong_to_a_pair(db: Database) -> None:
    """'our anniversary' is lowercase but it is not a pronoun."""
    found = extract_reminders("our anniversary is on 12 May")
    assert found and found[0]["name"] == "our"


def test_extraction_is_idempotent_across_reprocesses(db: Database) -> None:
    text = "Priya's birthday is on March 3 and our anniversary is on 12 May"
    assert extract_and_store(db, text) == 2
    assert extract_and_store(db, text) == 0
    assert len(list_reminders(db)) == 2


# ---- the HTTP surface ----------------------------------------------------


def test_the_endpoint_lists_what_is_due(client) -> None:
    db = client.app.state.st.db
    _add(db, "Priya", "birthday", 10, 20)
    r = client.get("/api/activity/reminders")
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "Priya"


def test_a_reminder_can_be_corrected_over_http(client) -> None:
    db = client.app.state.st.db
    _add(db, "Priya", "birthday", 10, 20)
    rid = db.list_reminders()[0]["id"]

    r = client.patch(f"/api/activity/reminders/{rid}", json={"changes": {"day": 25}})

    assert r.status_code == 200
    assert db.get_reminder(rid)["day"] == 25


def test_a_wrong_date_is_rejected_over_http(client) -> None:
    """Extraction rejects Feb 30; the correction path must too.

    This was the one way to store a date that does not exist, and a reminder
    on Feb 30 never fires on the right day.
    """
    db = client.app.state.st.db
    _add(db, "Priya", "birthday", 10, 20)
    rid = db.list_reminders()[0]["id"]

    r = client.patch(
        f"/api/activity/reminders/{rid}", json={"changes": {"month": 2, "day": 30}}
    )

    assert r.status_code == 422
    row = db.get_reminder(rid)
    assert (row["month"], row["day"]) == (10, 20), "the stored value must be untouched"


def test_deleting_over_http_sticks(client) -> None:
    db = client.app.state.st.db
    _add(db, "Priya", "birthday", 10, 20)
    rid = db.list_reminders()[0]["id"]

    assert client.delete(f"/api/activity/reminders/{rid}").status_code == 200
    assert db.list_reminders() == []
    assert client.get("/api/activity/reminders").json()["count"] == 0
