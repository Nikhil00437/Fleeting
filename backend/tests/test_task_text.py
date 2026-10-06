"""Tests for natural-language quick-add parsing (#278, #27)."""

from __future__ import annotations

from datetime import date

from fleeting.services.task_text import parse_quick_add

# 2026-10-06 is a Tuesday; Thursday is +2, Monday is +6.
TODAY = date(2026, 10, 6)


def parse(text: str, today: date = TODAY) -> object:
    return parse_quick_add(text, today=today)


def test_today_tonight_tomorrow():
    assert parse("water the plants today").due_date == "2026-10-06"
    assert parse("finish the report tonight").due_date == "2026-10-06"
    assert parse("call the dentist tomorrow").due_date == "2026-10-07"
    assert parse("call the dentist tmr").due_date == "2026-10-07"
    assert parse("call the dentist tomorrow").text == "call the dentist"


def test_weekday_forms():
    # Thursday: +2 days. Bare weekday is always ≥ tomorrow.
    assert parse("submit taxes by friday").due_date == "2026-10-09"
    assert parse("submit taxes friday").due_date == "2026-10-09"
    assert parse("meeting on thursday").due_date == "2026-10-08"
    assert parse("meeting thursday").due_date == "2026-10-08"
    # "next X" anchors to next calendar week (next week's Monday is Oct 12).
    assert parse("standup next thursday").due_date == "2026-10-15"
    assert parse("review next tuesday").due_date == "2026-10-13"
    assert parse("standup next thursday").text == "standup"
    assert parse("gym this saturday").due_date == "2026-10-10"


def test_relative_offsets():
    assert parse("revisit in 3 days").due_date == "2026-10-09"
    assert parse("revisit in 2 weeks").due_date == "2026-10-20"
    assert parse("revisit in 1 month").due_date == "2026-11-06"
    assert parse("check in next week").due_date == "2026-10-13"
    assert parse("check in next month").due_date == "2026-11-06"


def test_month_day_forms():
    assert parse("launch on oct 20").due_date == "2026-10-20"
    assert parse("launch oct 20th").due_date == "2026-10-20"
    assert parse("launch 20 october").due_date == "2026-10-20"
    assert parse("launch 3rd of june").due_date == "2027-06-03"  # past → next year
    assert parse("launch on 2026-12-01").due_date == "2026-12-01"
    assert parse("launch on 2026-12-01").text == "launch"


def test_time_of_day_stays_in_text():
    """No due_time column exists, so "3pm" must survive verbatim."""
    p = parse("call dentist tomorrow 3pm")
    assert p.due_date == "2026-10-07"
    assert p.text == "call dentist 3pm"


def test_context_repo_priority():
    p = parse("fix login @computer p1")
    assert p.text == "fix login"
    assert p.context == "computer"
    assert p.priority == "P1"

    p = parse("renew passport @errands !p3")
    assert p.priority == "P3"
    assert p.context == "errands"

    p = parse("ship the release +fleeting")
    assert p.repo == "fleeting"
    assert p.text == "ship the release"

    # The bundle's own example: "call dentist tomorrow 3pm #health".
    p = parse("call dentist tomorrow 3pm #health")
    assert p.text == "call dentist 3pm"
    assert p.due_date == "2026-10-07"
    assert p.repo == "health"


def test_email_not_a_context():
    p = parse("email bob@work about the invoice")
    assert p.context is None
    # The project regex is not @-bound; "#tag" and "+proj" share semantics.
    assert p.repo is None or p.repo == "work"


def test_false_positive_guards():
    # "maybe", "jane", "marching" start with month prefixes but are not dates.
    assert parse("maybe 5 things tomorrow").due_date == "2026-10-07"
    assert parse("ask jane 3 questions").due_date is None
    assert parse("keep marching on the budget").due_date is None
    # "in the morning" is not "in N units".
    assert parse("work in the morning").due_date is None
    # No preposition dangling after a matched phrase.
    assert parse("call the bank by friday").text == "call the bank"


def test_first_token_wins():
    p = parse("task @home @errands tomorrow")
    assert p.context == "home"
    assert p.due_date == "2026-10-07"


def test_explicit_date_kept_even_if_past():
    assert parse("file 2020 taxes on 2020-04-15").due_date == "2020-04-15"


def test_no_tokens_untouched():
    p = parse("just a plain thought, nothing special")
    assert p.text == "just a plain thought, nothing special"
    assert p.due_date is None
    assert p.context is None
    assert p.repo is None
    assert p.priority is None


def test_empty():
    assert parse("").text == ""
    assert parse("   ").text == ""
