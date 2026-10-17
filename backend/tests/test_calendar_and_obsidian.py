"""#123 local calendar import.

The property that matters most is about what the parser *refuses to do*: a
recurrence it cannot expand is **reported with its rule attached**, never silently
dropped. Silently losing a recurring meeting is how a calendar integration becomes
something people stop trusting, and the failure is invisible — the calendar just
looks emptier than it is.

`FREQ=DAILY/WEEKLY/MONTHLY/YEARLY` with `INTERVAL`, `COUNT` and `UNTIL` covers
almost everything in a personal calendar. `BYSETPOS` and `FREQ=MONTHLY;BYDAY=2TU`
are listed as skipped rather than approximated, because a standup that lands on
the wrong Tuesday is worse than one that is visibly absent.

Also pinned: a date-only `DTSTART` stays a date (an all-day event is a date; a
timed one is an instant — collapsing them is how a 14:00 meeting ends up on the
wrong day), folded lines are unfolded per RFC 5545, and both the event count and
each recurrence's expansion are bounded with the truncation *reported*.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from fleeting.services import calendar_import as ci


def ics(*events: str) -> str:
    body = "\n".join(events)
    return "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//test//EN\n" + body + "\nEND:VCALENDAR\n"


def event(summary: str = "Standup", start: str = "20260105T090000", **extra) -> str:
    """One VEVENT. `extra` keys become content lines, so pass `NAME="value"`.

    The `NAME=value` spelling here is converted to `NAME:value` — an ICS content
    line is colon-separated, and the first version of this helper wrote `=`,
    which the parser reads as a property with an empty value and silently drops.
    Duplicate keys are a dict's problem, so repeat lines via a tuple value.
    """
    lines = ["BEGIN:VEVENT", f"UID:{summary}-{start}", f"SUMMARY:{summary}", f"DTSTART:{start}"]
    for key, value in extra.items():
        for one in (value if isinstance(value, tuple) else (value,)):
            lines.append(f"{key}:{one}")
    lines += ["END:VEVENT"]
    return "\n".join(lines)


# ---- the basics ------------------------------------------------------------


def test_one_event_parses() -> None:
    parsed = ci.parse_ics(ics(event()))
    assert len(parsed["events"]) == 1
    assert parsed["events"][0]["summary"] == "Standup"


def test_a_timed_event_is_not_an_all_day_event() -> None:
    """Collapsing the two is how a 14:00 meeting ends up on the wrong day."""
    parsed = ci.parse_ics(ics(event(start="20260105T140000")))
    assert parsed["events"][0]["all_day"] is False


def test_a_date_only_event_is_all_day() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105")))
    assert parsed["events"][0]["all_day"] is True
    assert parsed["events"][0]["date"] == "2026-01-05"


def test_an_end_time_is_kept() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", DTEND="20260105T093000")))
    start = datetime.fromisoformat(parsed["events"][0]["start"])
    end = datetime.fromisoformat(parsed["events"][0]["end"])
    assert end - start == timedelta(minutes=30)


def test_a_location_is_read() -> None:
    parsed = ci.parse_ics(ics(event(LOCATION="Room 2")))
    assert parsed["events"][0]["location"] == "Room 2"


def test_escaped_characters_are_unescaped() -> None:
    parsed = ci.parse_ics(ics(event(summary="Lunch\\, and chat")))
    assert parsed["events"][0]["summary"] == "Lunch, and chat"


def test_a_utc_event_is_marked() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000Z")))
    assert parsed["events"][0]["tz"] == "Z"


def test_folded_lines_are_joined() -> None:
    """RFC 5545 folds at 75 octets; a continuation starts with a space."""
    folded = (
        "BEGIN:VEVENT\nUID:long\nDTSTART:20260105T090000\n"
        "SUMMARY:A summary that has been\n  folded across lines\nEND:VEVENT"
    )
    parsed = ci.parse_ics(ics(folded))
    assert "folded across lines" in parsed["events"][0]["summary"]


def test_attendees_are_counted() -> None:
    parsed = ci.parse_ics(ics(event(ATTENDEE=("mailto:a@x", "mailto:b@x"))))
    assert parsed["events"][0]["attendees"] == 2


def test_a_file_that_is_not_a_calendar_is_refused(tmp_path) -> None:
    bad = tmp_path / "notes.ics"
    bad.write_text("just some text")
    with pytest.raises(ci.CalendarError):
        ci.load(bad)


def test_a_missing_file_is_refused(tmp_path) -> None:
    with pytest.raises(ci.CalendarError):
        ci.load(tmp_path / "gone.ics")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ci.CalendarError):
        ci.parse_ics("")


# ---- recurrence ------------------------------------------------------------


def test_a_daily_recurrence_expands() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=DAILY;COUNT=3")))
    assert len(parsed["events"]) == 3


def test_a_daily_interval_expands_every_n_days() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=DAILY;INTERVAL=3;COUNT=3")))
    dates = [e["date"] for e in parsed["events"]]
    assert dates == ["2026-01-05", "2026-01-08", "2026-01-11"]


def test_a_weekly_recurrence_expands() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=WEEKLY;COUNT=2")))
    assert [e["date"] for e in parsed["events"]] == ["2026-01-05", "2026-01-12"]


def test_a_monthly_recurrence_handles_a_short_month() -> None:
    """The 31st does not exist in February, and a recurrence that crashes on it
    loses every event after it."""
    parsed = ci.parse_ics(ics(event(start="20260131T090000", RRULE="FREQ=MONTHLY;COUNT=3")))
    assert [e["date"] for e in parsed["events"]] == [
        "2026-01-31",
        "2026-02-28",
        "2026-03-31",
    ]


def test_until_stops_the_recurrence() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=DAILY;UNTIL=20260107T000000")))
    assert len(parsed["events"]) == 3


def test_an_excluded_date_is_skipped() -> None:
    parsed = ci.parse_ics(
        ics(event(start="20260105T090000", RRULE="FREQ=DAILY;COUNT=3", EXDATE="20260106T090000"))
    )
    assert [e["date"] for e in parsed["events"]] == ["2026-01-05", "2026-01-07"]


def test_an_expansion_is_bounded() -> None:
    """A ten-year daily standup is 3,650 instances, which is not a calendar."""
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=DAILY")))
    assert len(parsed["events"]) <= ci.MAX_EXPANSIONS + 1


def test_an_unsupported_recurrence_is_reported_not_dropped() -> None:
    """Silently losing a recurring meeting is how a calendar integration becomes
    something people stop trusting."""
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=MONTHLY;BYDAY=2TU")))
    assert parsed["events"] == []
    assert parsed["skipped"], "the skipped event must be reported"
    assert "BYDAY" in parsed["skipped"][0]["reason"]


def test_the_skip_names_the_rule_so_the_user_can_report_it() -> None:
    parsed = ci.parse_ics(ics(event(RRULE="FREQ=YEARLY;BYMONTH=3")))
    assert "RRULE" in parsed["skipped"][0]["reason"]


def test_an_unsupported_frequency_is_also_named() -> None:
    """The frequency branch and the `BY*` branch are separate rejections, and
    only the second was covered — so a reason-less skip passed as 'reported'."""
    parsed = ci.parse_ics(ics(event(RRULE="FREQ=HOURLY")))
    assert parsed["events"] == []
    reason = parsed["skipped"][0]["reason"]
    assert reason
    assert "FREQ=HOURLY" in reason


def test_every_skip_has_a_reason() -> None:
    """A skip with an empty reason is invisible to whoever reads the report."""
    for rule in ("FREQ=HOURLY", "FREQ=MONTHLY;BYDAY=2TU", "FREQ=WEEKLY;WKST=SU"):
        parsed = ci.parse_ics(ics(event(RRULE=rule)))
        assert parsed["skipped"], rule
        for skip in parsed["skipped"]:
            assert skip["reason"].strip(), rule


def test_a_second_occurrence_keeps_the_same_summary() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000", RRULE="FREQ=DAILY;COUNT=2")))
    assert {e["summary"] for e in parsed["events"]} == {"Standup"}


def test_an_event_with_no_dtstart_is_skipped() -> None:
    parsed = ci.parse_ics(ics("BEGIN:VEVENT\nUID:x\nSUMMARY:broken\nEND:VEVENT"))
    assert parsed["events"] == []
    assert parsed["skipped"]


# ---- day views -------------------------------------------------------------


def test_for_one_day_returns_that_day() -> None:
    parsed = ci.parse_ics(ics(event(start="20260105T090000"), event("Other", start="20260106T090000")))
    rows = ci.for_day(parsed, date(2026, 1, 5))
    assert [r["summary"] for r in rows] == ["Standup"]


def test_timed_events_come_before_all_day_ones() -> None:
    """The order a day view actually reads in."""
    parsed = ci.parse_ics(
        ics(event("All day", start="20260105"), event("Meeting", start="20260105T140000"))
    )
    assert [r["summary"] for r in ci.for_day(parsed, date(2026, 1, 5))] == ["Meeting", "All day"]


def test_an_empty_day_is_empty_not_an_error() -> None:
    parsed = ci.parse_ics(ics(event()))
    assert ci.for_day(parsed, date(2030, 1, 1)) == []


# ---- discovery -------------------------------------------------------------


def test_calendar_files_are_discovered_under_a_folder(tmp_path) -> None:
    """Searched rather than configured: calendar exports go somewhere different on
    every platform, and a hardcoded list is wrong on all of them."""
    (tmp_path / "cal").mkdir()
    (tmp_path / "cal" / "work.ics").write_text(ics(event()))
    (tmp_path / "cal" / "personal.ics").write_text(ics(event()))
    found = ci.discover([tmp_path])
    assert {p.name for p in found} == {"work.ics", "personal.ics"}


def test_discovery_is_bounded(tmp_path) -> None:
    for i in range(30):
        (tmp_path / f"c{i}.ics").write_text(ics(event()))
    assert len(ci.discover([tmp_path], limit=5)) == 5


def test_a_missing_folder_is_not_an_error(tmp_path) -> None:
    assert ci.discover([tmp_path / "nope"]) == []


# ---- the endpoints ---------------------------------------------------------


def test_the_endpoint_loads_a_file(client, tmp_path) -> None:
    f = tmp_path / "work.ics"
    f.write_text(ics(event(start="20260105T090000"), event("Weekly", start="20260106T090000", RRULE="FREQ=WEEKLY;COUNT=2")))
    body = client.post("/api/calendar/import", json={"path": str(f)}).json()
    assert body["counts"]["parsed"] == 3


def test_the_endpoint_reports_a_bad_file(client, tmp_path) -> None:
    f = tmp_path / "nope.ics"
    f.write_text("not a calendar")
    assert client.post("/api/calendar/import", json={"path": str(f)}).status_code == 400


def test_the_day_endpoint_returns_that_day(client, tmp_path) -> None:
    f = tmp_path / "work.ics"
    f.write_text(ics(event(start="20260105T090000")))
    client.post("/api/calendar/import", json={"path": str(f)})
    body = client.get("/api/calendar/day?date=2026-01-05").json()
    assert [e["summary"] for e in body["events"]] == ["Standup"]

# ---- #134: Obsidian URIs ---------------------------------------------------


def test_the_obsidian_url_names_the_vault_and_the_file(client) -> None:

    st = client.app.state.st
    st.db.insert_note({"id": "n1", "title": "A note", "type": "text", "created_at": "2026-01-02T09:00:00+00:00", "tags": []})
    st.db.commit()
    body = client.get("/api/vault/obsidian/n1").json()
    assert body["available"] is True
    assert body["vault"] == "vault", "Obsidian resolves by vault name, not by path"
    assert body["file"].endswith(".md")
    assert body["url"].startswith("obsidian://open?vault=vault&file=")


def test_the_obsidian_url_argument_has_no_extension_or_leading_slash(client) -> None:
    """Obsidian wants the path without `.md` and relative to the vault root.

    Checked on the *URL*, because that is what Obsidian receives. The `file`
    field keeps the extension — it is for showing the user where the note went.
    """
    from urllib.parse import parse_qs, urlparse

    st = client.app.state.st
    st.db.insert_note({"id": "n1", "title": "t", "type": "text", "created_at": "2026-01-02T09:00:00+00:00", "tags": []})
    st.db.commit()
    body = client.get("/api/vault/obsidian/n1").json()
    assert body["file"].endswith(".md"), "the displayed path is the real filename"

    file_arg = parse_qs(urlparse(body["url"]).query)["file"][0]
    assert not file_arg.endswith(".md")
    assert not file_arg.startswith("/")


def test_special_characters_are_percent_encoded(tmp_path) -> None:
    """Spaces, `#` and `&` are all common in note filenames, and an unencoded
    `&` truncates the query string."""
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import obsidian_uri

    from urllib.parse import parse_qs, urlparse

    cfg = PathsConfig(vault_dir=str(tmp_path / "My Vault & Co"))
    note = {"id": "a b&c", "title": "t", "created_at": "2026-01-02T09:00:00+00:00"}
    body = obsidian_uri(cfg, note)
    # The vault name has two query parameters' worth of trouble in it: a space
    # and an `&` that would otherwise end the parameter.
    query = parse_qs(urlparse(body["url"]).query)
    assert query["vault"] == ["My Vault & Co"]
    assert set(query) == {"vault", "file"}, f"the & in the vault name leaked a parameter: {query}"
    assert " " not in body["url"]


def test_no_folder_template_can_put_a_note_outside_the_vault(tmp_path) -> None:
    """The invariant that makes `obsidian_uri`'s outside-the-vault branch
    unreachable through normal use.

    Written as containment rather than "the branch returns a message" because
    the branch is only reachable if `vault_path_for` can escape — and it cannot.
    Asserting the branch's output would test a path that never happens; this
    tests the reason it never happens.
    """
    from fleeting.config import PathsConfig
    from fleeting.services.markdown import vault_path_for

    root = (tmp_path / "vault").resolve()
    note = {"id": "n1", "title": "t", "created_at": "2026-01-02T09:00:00+00:00"}
    for template in (
        "../escaped",
        "../../etc",
        "/absolute/{{year}}",
        "{{year}}",
        "a/../../b",
        "{{first_tag}}",
        "Inbox/{{type}}",
        "",
    ):
        cfg = PathsConfig(vault_dir=str(root))
        cfg.vault_folder_template = template
        path = vault_path_for(cfg, note).resolve()
        assert str(path).startswith(str(root)), f"{template!r} escaped to {path}"


def test_a_note_whose_file_is_outside_the_vault_says_so(tmp_path, monkeypatch) -> None:
    """The guard itself, reached with a stub.

    `folder_for` already makes this unreachable through normal use — that is what
    `test_no_folder_template_can_put_a_note_outside_the_vault` pins. This reaches
    the branch anyway, because an untested guard is a guard nobody knows works: if
    a future change makes the path escape, this is the behaviour that has to hold
    and the message has to be the one a user can act on.
    """
    import pathlib as _pathlib

    from fleeting.config import PathsConfig
    from fleeting.services import markdown

    monkeypatch.setattr(
        markdown, "vault_path_for", lambda cfg, note: _pathlib.Path("/elsewhere/note.md")
    )
    body = markdown.obsidian_uri(PathsConfig(vault_dir=str(tmp_path / "vault")), {"id": "n1"})
    assert body["available"] is False
    assert "outside the configured vault" in body["reason"]
    assert "url" not in body, "a link that opens the wrong thing is worse than no link"


def test_an_unknown_note_is_404(client) -> None:
    assert client.get("/api/vault/obsidian/nope").status_code == 404
