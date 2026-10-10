"""#259 local-only sentiment and urgency flags.

Neither flag calls a model. That is the requirement, not a shortcut: a flag
that changes when the LLM is swapped, or disappears when LM Studio is closed,
cannot be sorted against, and a note list whose order quietly changes under
the user is worse than one with no order at all.

So both are word- and date-based, and both return their reasons. An
inexplicable flag is a flag nobody can correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.db import Database
from fleeting.services.tone import sentiment, tone_of, urgency


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "tone.db"))
    database.migrate()
    return database


def _note(text: str, **kw) -> dict:
    base = {"id": "n1", "title": "", "raw_text": text, "summary": "", "tags": []}
    return {**base, **kw}


# ---- urgency -------------------------------------------------------------


def test_plain_prose_has_no_urgency() -> None:
    assert urgency(_note("bought milk and walked the dog")) == ("none", [])


def test_deadline_words_raise_urgency() -> None:
    for phrase in ("this is urgent", "do it asap", "need it by eod", "deadline is friday"):
        level, reasons = urgency(_note(phrase))
        assert level == "high", phrase
        assert reasons, "a flag with no reason cannot be corrected"


def test_an_implied_deadline_counts_too() -> None:
    level, reasons = urgency(_note("send the report tomorrow"))
    assert level in ("low", "high")
    assert reasons


def test_a_note_with_an_overdue_task_is_high(db: Database) -> None:
    """The strongest signal: the user already put a date on this work."""
    note_id = db.insert_note({"title": "t", "raw_text": "b", "status": "done"})["id"]
    db.insert_task({"text": "file the taxes", "due_date": "2020-01-01", "note_id": note_id})

    level, reasons = urgency(_note("nothing urgent in the words", id=note_id), db, today="2026-10-11")

    assert level == "high"
    assert any("overdue" in r.lower() for r in reasons)


def test_a_note_whose_tasks_are_all_done_is_not_urgent(db: Database) -> None:
    note_id = db.insert_note({"title": "t", "raw_text": "b", "status": "done"})["id"]
    task = db.insert_task({"text": "done thing", "due_date": "2020-01-01", "note_id": note_id})
    db.update_task(task["id"], {"done": 1})

    assert urgency(_note("calm text", id=note_id), db, today="2026-10-11")[0] == "none"


def test_urgency_needs_no_model(db: Database) -> None:
    """Signature takes no config at all, so it cannot reach one."""
    level, _ = urgency(_note("urgent"))
    assert level == "high"


# ---- sentiment -----------------------------------------------------------


def test_neutral_text_is_not_glossed_as_a_mood() -> None:
    assert sentiment(_note("the build passed in four minutes"))[0] == "neutral"


def test_positive_words_are_seen() -> None:
    assert sentiment(_note("this shipped beautifully and everyone loved it"))[0] == "positive"


def test_negative_words_are_seen() -> None:
    assert sentiment(_note("this is broken and I am frustrated"))[0] == "negative"


def test_the_winning_side_takes_it() -> None:
    assert sentiment(_note("lovely but broken and awful"))[0] == "negative"


def test_a_tie_stays_neutral() -> None:
    """One word each way is not a signal, and guessing would be noise."""
    assert sentiment(_note("loved this, hated that"))[0] == "neutral"


def test_sentiment_needs_no_model(db: Database) -> None:
    assert sentiment(_note("wonderful"))[0] == "positive"


# ---- the pair ------------------------------------------------------------


def test_both_flags_come_back_together(db: Database) -> None:
    tone_of(_note("urgent: the fix is wonderful"), db, today="2026-10-11")


def test_a_notes_flags_are_computable_without_its_tasks(db: Database) -> None:
    """A note with no rows in the tasks table must still produce a tone."""
    out = tone_of(_note("nothing special here"), db, today="2026-10-11")
    assert out["urgency"] == "none"
    assert out["sentiment"] == "neutral"


# ---- the endpoint --------------------------------------------------------


def test_the_tone_endpoint_sorts_by_urgency(client) -> None:
    db = client.app.state.st.db
    db.insert_note({"title": "calm", "raw_text": "bought milk", "status": "done"})
    db.insert_note({"title": "shouty", "raw_text": "urgent asap", "status": "done"})

    r = client.get("/api/notes/tone")

    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["title"] for i in items][:2] == ["shouty", "calm"]
    assert items[0]["urgency"] == "high"
    assert "urgency_reasons" in items[0]


def test_the_tone_endpoint_can_filter_to_one_sentiment(client) -> None:
    db = client.app.state.st.db
    db.insert_note({"title": "happy", "raw_text": "wonderful lovely great", "status": "done"})
    db.insert_note({"title": "sad", "raw_text": "broken awful terrible", "status": "done"})

    r = client.get("/api/notes/tone", params={"sentiment": "negative"})

    assert [i["title"] for i in r.json()["items"]] == ["sad"]


# ---- whole tokens, not substrings ----------------------------------------
#
# Substring matching on short words is how a heuristic starts lying: "now" is
# inside "snow" and "know", so a note about a ski trip would read as a
# deadline. Found by mutation, not by reading the code.


def test_a_word_that_merely_contains_a_token_is_not_urgent() -> None:
    level, reasons = urgency(_note("we saw snow in the mountains and I know nothing about it"))
    assert level == "none", reasons


def test_a_word_that_merely_contains_a_token_is_not_a_mood() -> None:
    """'bug' sits inside 'debug', which is where the work is, not a defect."""
    assert sentiment(_note("spent the morning in the debugger"))[0] == "neutral"


def test_the_token_itself_still_fires() -> None:
    """A guard against over-correcting into matching nothing at all."""
    assert urgency(_note("do this now"))[0] == "high"
