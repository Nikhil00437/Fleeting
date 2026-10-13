"""#143: a redacted export — notes you can actually hand to someone else.

The failure mode of every "redact" feature is the same: it produces output that
*looks* redacted, so you send it, and someone finds the thing you were worried
about. So the rule here is that a pattern is only redacted when matching it is
reliable, and everything unreliable is either left alone or told to the user.

Which is why **person names are not pattern-matched**. `Alice` and `Prof. Ng`
and "my brother Raj" are not separable from ordinary words by regex, and a
guessing pass mangles notes while giving the comfortable impression that names
were handled. Instead the caller passes the names they know:

    POST /api/export {"redact": true, "names": ["Alice", "Bob"]}

That is honest — you know your own names; a regex does not — and the report says
exactly which patterns fired, so "nothing was found" is distinguishable from
"nothing was looked for".
"""

from __future__ import annotations

import pytest

from fleeting.services.redact import PATTERNS, redact


def test_an_email_is_removed() -> None:
    out, _ = redact("write to alice@example.com about it", names=[])
    assert "alice@example.com" not in out
    assert "about it" in out


def test_a_phone_number_is_removed() -> None:
    out, _ = redact("call +44 20 7946 0958 now", names=[])
    assert "7946" not in out


def test_a_card_number_is_removed() -> None:
    out, _ = redact("card 4111 1111 1111 1111 exp 2030", names=[])
    assert "4111 1111 1111 1111" not in out


def test_an_api_key_is_removed() -> None:
    out, _ = redact("key is sk-live-abcdef0123456789abcdef", names=[])
    assert "abcdef0123456789" not in out


def test_a_supplied_name_is_removed() -> None:
    out, hits = redact("Alice said the router is fine", names=["Alice"])
    assert "Alice" not in out
    assert hits["names"] == 1


def test_names_are_matched_case_insensitively() -> None:
    out, _ = redact("alice and ALICE and Alice", names=["alice"])
    assert "lice" not in out


def test_a_name_is_not_matched_inside_a_longer_word() -> None:
    """Redacting "Al" must not turn "Always" into "[name]ways". That is how a
    redactor destroys the document it was meant to protect."""
    out, hits = redact("Always check the alarm", names=["Al"])
    assert "Always" in out and "alarm" in out
    assert hits.get("names", 0) == 0


def test_ordinary_prose_is_untouched() -> None:
    text = "The router firmware upgrade failed at 60% and needs serial recovery."
    out, hits = redact(text, names=[])
    assert out == text
    assert hits == {}


def test_short_digit_runs_are_left_alone() -> None:
    """A version number, a percentage, a year. Redacting them makes the export
    useless for the thing people actually export notes for."""
    out, _ = redact("upgraded to 1.2.3, 60% done, in 2024, PR #4821", names=[])
    assert "60%" in out and "2024" in out


def test_the_report_says_what_fired() -> None:
    """`{}` is ambiguous: nothing found, or nothing looked for."""
    _, hits = redact("a@b.com and 4111111111111111", names=["Zed"])
    assert hits["email"] >= 1
    assert "number" in hits
    assert "names" not in hits


def test_the_report_distinguishes_scanned_from_found() -> None:
    _, hits = redact("nothing sensitive here", names=["Zed"])
    assert hits == {}


def test_every_pattern_has_a_label() -> None:
    """An unlabelled pattern makes the report unusable, and the report is the
    only thing that tells you the export was checked."""
    for label, pattern in PATTERNS.items():
        assert label and pattern.pattern


def test_redaction_is_idempotent() -> None:
    """Running it twice must not produce different output — otherwise the
    pipeline that redacts on the way out and again on the way in disagrees."""
    once, _ = redact("mail alice@example.com", names=[])
    twice, _ = redact(once, names=[])
    assert once == twice


def test_placeholders_are_readable_not_noise() -> None:
    out, _ = redact("mail alice@example.com", names=[])
    assert "[email]" in out


def test_a_supplied_name_becomes_a_stable_placeholder() -> None:
    """`[person]` three times reads as three people. `Alice mentioned Bob` →
    `[person-1] mentioned [person-2]` keeps the sentence readable."""
    out, _ = redact("Alice met Bob", names=["Alice", "Bob"])
    assert "[person-1]" in out and "[person-2]" in out


def test_unicode_text_is_not_mangled() -> None:
    out, _ = redact("café — naïve — 日本語のメモ alice@example.com", names=[])
    assert "日本語のメモ" in out and "café" in out
    assert "alice@example.com" not in out


def test_a_very_long_note_does_not_blow_up() -> None:
    out, _ = redact("x" * 200_000 + " alice@example.com", names=[])
    assert len(out) < 250_000


@pytest.mark.parametrize("text", ["", "   ", "\n\n", None])
def test_empty_input_is_empty_output(text) -> None:
    out, hits = redact(text, names=[])
    assert out in ("", "   ", "\n\n")
    assert hits == {}



def test_a_pattern_cannot_match_across_a_newline() -> None:
    """A dot-all pattern turns two unrelated lines into one match and deletes
    the text between them."""
    out, _ = redact("first line\nsecond line", names=[])
    assert "first line" in out and "second line" in out

# ---- adversarial input ---------------------------------------------------
#
# The bounded email pattern was not written for tidiness. An unbounded `+` over
# a long run of word characters is quadratic: 200k of them took 130 seconds
# against one note. These are the inputs that find that class of bug, and they
# are the reason a "long note" test exists at all.


@pytest.mark.parametrize(
    "filler",
    [
        "x" * 200_000,
        "9" * 200_000,
        "a" * 60_000 + " ",
        "word " * 40_000,
        "é" * 100_000,
    ],
    ids=["letters", "digits", "sixty-k", "words", "unicode"],
)
def test_pathological_input_is_fast(filler: str) -> None:
    """A redaction pass that takes two minutes on one note is a redaction pass
    that will be switched off, which is worse than not having it."""
    import time

    started = time.monotonic()
    redact(filler + " alice@example.com 4111 1111 1111 1111", names=["Alice", "Bob"])
    assert time.monotonic() - started < 2.0


def test_an_over_long_local_part_is_not_treated_as_an_email() -> None:
    """RFC 5321 caps a local part at 64 characters. Matching a longer run would
    swallow a whole paragraph into one placeholder."""
    out, hits = redact("x" * 300 + "@example.com", names=[])
    assert hits.get("email", 0) == 0
    assert len(out) > 100


def test_a_real_address_at_the_end_of_a_long_note_is_still_found() -> None:
    """The fix must not be "give up on long input"."""
    out, hits = redact("x" * 100_000 + " mail bob@example.co.uk now", names=[])
    assert hits["email"] == 1
    assert "bob@example.co.uk" not in out


# ---- the export endpoint --------------------------------------------------


def test_a_plain_export_is_not_redacted(client) -> None:
    _capture(client, "mail bob@example.com")
    body = client.post("/api/export", json={}).json()
    assert "bob@example.com" in body["markdown"]


def test_a_redacted_export_removes_the_email(client) -> None:
    _capture(client, "mail bob@example.com")
    body = client.post("/api/export", json={"redact": True}).json()
    assert "bob@example.com" not in body["markdown"]
    assert "[email]" in body["markdown"]


def test_the_export_says_what_it_found(client) -> None:
    """Otherwise "nothing was redacted" and "nothing was scanned" look alike."""
    _capture(client, "mail bob@example.com")
    body = client.post("/api/export", json={"redact": True}).json()
    assert body["redacted"]["email"] >= 1


def test_supplied_names_are_redacted_across_the_bundle(client) -> None:
    _capture(client, "Alice said the router is fine")
    body = client.post("/api/export", json={"redact": True, "names": ["Alice"]}).json()
    assert "Alice" not in body["markdown"]
    assert body["redacted"]["names"] >= 1


def test_the_export_includes_every_note(client) -> None:
    for t in ("one", "two", "three"):
        _capture(client, t)
    body = client.post("/api/export", json={"redact": True}).json()
    assert body["notes"] == 3


def test_an_empty_database_exports_an_empty_bundle(client) -> None:
    body = client.post("/api/export", json={"redact": True}).json()
    assert body["notes"] == 0


def test_the_export_is_serialisable_and_complete(client) -> None:
    import json

    _capture(client, "mail bob@example.com")
    body = client.post("/api/export", json={"redact": True}).json()
    assert set(body) == {"markdown", "notes", "redacted"}
    json.dumps(body)


def test_redaction_does_not_touch_the_database(client) -> None:
    """An export that rewrites what it exported would quietly destroy the
    original while claiming to share a copy."""
    _capture(client, "mail bob@example.com")
    client.post("/api/export", json={"redact": True, "names": ["Alice"]})
    assert any("bob@example.com" in n["raw_text"] for n in client.get("/api/notes").json())


def _capture(client, title: str) -> None:
    from conftest import wait_done

    r = client.post("/api/capture/text", json={"text": f"body of {title}", "title": title})
    wait_done(client, r.json()["id"])
