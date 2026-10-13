"""#391 property tests for the markdown/vault round-trip.

0.10 (vault sync) and 0.15 (knowledge work) both rewrite notes through this
renderer, so the round-trip is load-bearing: anything the parser cannot read
back is content the vault silently eats.

Written without Hypothesis, deliberately. The interesting inputs are not
arbitrary unicode — a composed generator builds each field from a list of
fragments known to break naive markdown handling (`---`, `title: x`, `#`, a
checkbox bullet, blank lines), which means **every generated case is already
its own minimal repro** and nothing needs shrinking. Hypothesis would add a
dependency to solve a problem this shape of generator does not have.

The corpus is fixed and the seed is pinned, so a CI failure reproduces
byte-for-byte rather than needing a replay.

What is asserted is the *content* round-trip, not bytes: whitespace at the
edges of a title is normalised away on purpose, and a title containing a
newline is truncated on purpose (titles are single-line). Asserting bytes would
mean locking in the normalisers instead of the contract.
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path

import pytest

from fleeting.config import PathsConfig
from fleeting.services.markdown import (
    note_filename,
    parse_note_md,
    render_note_md,
    vault_path_for,
)

# Fragments that break naive markdown handling. Each one has cost this
# codebase a bug at some point or would in a review.
NASTY_FRAGMENTS = (
    "---",
    "title: looks like frontmatter",
    "# heading",
    "## another",
    "- [ ] an open checkbox",
    "- [x] a done checkbox",
    "[a link](http://example.invalid)",
    "`inline code`",
    "```fenced```",
    "a | pipe | inside",
    "**bold** and _italic_",
    "<script>alert(1)</script>",
    "unicode: ünïcode 😀 日本語",
    "trailing spaces   ",
    "a\ttab",
    "",
    " ",
    "\n",
    "text with : colon = equals",
    "> a quote",
    "1. an ordered item",
    "TODO: something",
)

BODIES = (
    "",
    "One line with no punctuation",
    "Two paragraphs.\n\nWith a blank line between them.",
    "A body containing --- in the middle.\nAnd more after it.",
    "A body that looks like frontmatter:\ntitle: nope\ntags: [nope]",
    "Markdown bullets:\n- one\n- two\n\nAnd a closing paragraph.",
    "Trailing blank lines follow.\n\n\n",
    "A tab\tinside a line.",
)

TITLES = (
    "Router firmware notes",
    "A title with a colon: in it",
    "A title with # a hash",
    "A title with --- dashes",
    "A title with [brackets]",
    "  padded  ",
    "unicode ünïcode 😀",
    "",
)

# Actual traversal payloads. The markdown fragments above are dangerous to a
# parser; these are dangerous to the filesystem, and the two sets have no
# overlap — a corpus of only the first leaves the traversal path untested.
ATTACK_TITLES = (
    "../../etc/passwd",
    "..",
    "a/b/c",
    "/absolute/path",
    "~/secrets",
    "....//....//etc/shadow",
    "C:\\Windows\\System32",
    "note\x00.md",
)


TAG_SETS = (
    [],
    ["homelab"],
    ["homelab", "network", "router"],
    ["has space", "hash#inside", "dash-inside"],
    # Mixed case, because people write `#Router`. Every tag above was already
    # lowercase, so a renderer that lowercased them was invisible: mutating
    # `f"  - {t}"` to `f"  - {t.lower()}"` passed the whole file. Verified by
    # mutation, not assumed.
    ["Router", "NeedsReview"],
    ["MiXeD CaSe", "UPPER"],
)

TASK_SETS = (
    [],
    [{"text": "flash the firmware", "priority": "P1", "done": False}],
    [{"text": "done already", "priority": "P2", "done": True}],
    [
        {"text": "first", "priority": "P1", "done": False},
        {"text": "second — with a dash", "priority": "P3", "done": False},
    ],
)

SEED = 20261011

# `##` is excluded from the soup because it is a section marker in this format,
# covered by its own test below rather than folded into the round-trip claim.
BODY_FRAGMENTS = tuple(f for f in NASTY_FRAGMENTS if not f.startswith("##"))


def _note(title: str, body: str, tags: list[str], tasks: list[dict], i: int) -> dict:
    return {
        "id": f"prop{i:04d}",
        "title": title,
        "raw_text": body,
        "tags": tags,
        "action_items": tasks,
        "summary": "",
        "created_at": "2026-10-11T09:00:00+00:00",
        "type": "text",
        "pinned": 0,
        "archived": 0,
        "sensitive": 0,
        "review_state": "enriched",
        "fields": {},
        "starred": 0,
    }


def _expected_title(title: str) -> str:
    """What the parser must give back for this title.

    Two normalisers are deliberate and are part of the contract, not bugs:

    - an empty title renders as "Untitled capture" rather than an empty
      heading, so the vault file has something to open;
    - whitespace at the edges is stripped.

    A test that asserted the raw input here would be locking the normalisers
    in *as if* they were the round-trip, which is the opposite of what a
    property test is for.
    """
    return (title.strip() or "Untitled capture")


def _expected_body(body: str) -> str:
    """Bodies keep their interior exactly; whitespace at the edges is dropped.

    `render_note_md` does `(note.get("raw_text") or "").strip()` before it
    emits anything, so a body cannot round-trip its own leading or trailing
    whitespace. Trimming the edges is what makes the round-trip close;
    interior blank lines and indentation are load-bearing and are preserved.
    """
    return body.strip()


def _cases():
    """Every combination of the small sets — exhaustive, not sampled.

    Runs in well under a second and leaves no gap a random draw could miss.
    Randomness is then only used to build the adversarial *fragment* cases
    below.
    """
    for i, (title, body, tags, tasks) in enumerate(
        itertools.product(TITLES, BODIES, TAG_SETS, TASK_SETS)
    ):
        yield _note(title, body, tags, tasks, i)


# Built once and reused. The generator used to be called per test, and the id
# list was hardcoded to 1024 — so adding a tag set broke collection instead of
# adding coverage.
CASES = list(_cases())


# ---- the property ---------------------------------------------------------


@pytest.mark.parametrize("note", CASES, ids=range(len(CASES)))
def test_a_note_survives_the_round_trip(note: dict) -> None:
    """Every field, checked against the same 1024 notes.

    These were four tests over one identical corpus — 4096 cases to assert four
    properties of the same inputs. Merged, so each case runs the whole
    round-trip once and asserts everything about it. Same coverage, and a
    failure now names the case *and* the field rather than only the field.
    """
    parsed = parse_note_md(render_note_md(note))

    # The title. Whitespace at its edges is normalised away on purpose.
    assert (parsed.get("title") or "").strip() == _expected_title(note["title"])

    # The body is the thing that would be silently lost. Its interior is
    # load-bearing and survives exactly.
    assert parsed.get("raw_text") == _expected_body(note["raw_text"])

    assert sorted(parsed.get("tags") or []) == sorted(note["tags"])

    got = [
        {"text": a.get("text"), "done": bool(a.get("done")), "priority": a.get("priority")}
        for a in (parsed.get("action_items") or [])
    ]
    want = [
        {"text": a.get("text"), "done": bool(a.get("done")), "priority": a.get("priority")}
        for a in note["action_items"]
    ]
    assert got == want


def test_rendering_reaches_a_fixed_point() -> None:
    """The vault watcher reads a file and writes it back. That must settle.

    One pass is not always enough: a title of `"  padded  "` renders as
    `#   padded  `, and the parser trims it back to `padded`, so the first
    rewrite differs from the file on disk. What matters is that it converges —
    a note whose text changes on every pass would churn the user's vault
    forever, and that is the failure this pins down.

    Two passes are allowed, then everything must be stable.
    """
    rng = random.Random(SEED)
    for i in range(200):
        note = _note(
            rng.choice(TITLES),
            rng.choice(BODIES) + " " + "".join(
                rng.choice(NASTY_FRAGMENTS) for _ in range(rng.randint(0, 3))
            ),
            rng.choice(TAG_SETS),
            rng.choice(TASK_SETS),
            i,
        )
        once = render_note_md(note)
        twice = render_note_md(parse_note_md(once))
        assert twice == render_note_md(parse_note_md(twice)), note["title"]


# ---- the fragment soup, where the real bugs live --------------------------


def test_adversarial_bodies_survive() -> None:
    rng = random.Random(SEED)
    for i in range(400):
        body = "\n".join(
            rng.choice(BODY_FRAGMENTS) for _ in range(rng.randint(1, 6))
        )
        note = _note(rng.choice(TITLES), body, rng.choice(TAG_SETS), [], i)
        parsed = parse_note_md(render_note_md(note))
        assert parsed.get("raw_text") == _expected_body(body), f"lost body: {body!r}"


def test_a_heading_inside_a_body_is_a_section_marker() -> None:
    """`##` in a body is structure, and the format cannot tell otherwise.

    `parse_note_md` splits a note on `##`, so a heading written into the body
    of a capture becomes a section rather than text: sections are rejoined
    with a blank line, which is a normalisation rather than a loss. A body
    that *is* a heading round-trips byte-exact; one that merely precedes a
    heading gains a blank line at the boundary.

    Worth stating plainly because it is not fixable: any note whose content is
    genuinely a `## Action items` section will be read back as the note's
    action items. That is the format, and no test can make it otherwise.
    """
    note = _note("Real title", "intro\n## a heading mid-body", [], [], 0)
    parsed = parse_note_md(render_note_md(note))
    assert parsed.get("raw_text") == "intro\n\n## a heading mid-body"

    # A body that is nothing but a heading survives exactly.
    note = _note("Real title", "# just a heading", [], [], 0)
    assert parse_note_md(render_note_md(note)).get("raw_text") == "# just a heading"


def test_a_checklist_written_into_the_body_stays_body_text() -> None:
    """Body text is not silently promoted to action items.

    `_parse_checklist_items` also runs as a fallback over whatever precedes the
    first `##`, which is worth pinning: a capture that quotes a checklist stays
    quoted text instead of quietly becoming three tasks the user never made.
    """
    note = _note("Real title", "- [ ] do the thing\n- [x] done thing", [], [], 0)
    parsed = parse_note_md(render_note_md(note))
    assert parsed.get("action_items") == []
    assert parsed.get("raw_text") == "- [ ] do the thing\n- [x] done thing"


def test_a_body_that_is_only_frontmatter_looking_text() -> None:
    """The parser must not mistake a body for the note's own frontmatter."""
    body = "---\ntitle: I am a body, not metadata\ntags: [also, body]"
    note = _note("Real title", body, ["homelab"], [], 0)
    parsed = parse_note_md(render_note_md(note))
    assert parsed.get("title") == "Real title"
    assert parsed.get("raw_text") == body


# ---- filenames ------------------------------------------------------------


def test_filenames_are_unique_and_filesystem_safe(tmp_path: Path) -> None:
    """Two notes with the same title must not overwrite each other."""
    cfg = PathsConfig(vault_dir=str(tmp_path))
    a = _note("Same title", "one", [], [], 1)
    b = _note("Same title", "two", [], [], 2)
    assert vault_path_for(cfg, a) != vault_path_for(cfg, b)


@pytest.mark.parametrize("title", [*TITLES, *ATTACK_TITLES])
def test_a_title_never_escapes_the_vault(tmp_path: Path, title: str) -> None:
    """A title is user text; `../../etc/passwd` must not become a path."""
    cfg = PathsConfig(vault_dir=str(tmp_path / "vault"))
    note = _note(title, "body", [], [], 0)
    path = vault_path_for(cfg, note)
    # Resolved, so a symlink or a `..` that survives textually still fails.
    assert str(path.resolve()).startswith(str((tmp_path / "vault").resolve()))
    assert ".." not in path.name
    assert path.suffix == ".md"


@pytest.mark.parametrize("title", ATTACK_TITLES)
def test_an_attack_title_never_reaches_the_path(title: str) -> None:
    """Filenames are date + id, so no user text can steer the path.

    Worth a test even though the design makes it obvious: `note_filename`
    deliberately ignores the title ("no title slug, which churns"), and a
    future "friendlier" filenames-in-the-vault change would put this back. A
    title of `../../etc/passwd` must not become a path, and a title containing
    slashes must not create a directory.
    """
    name = note_filename(_note(title, "", [], [], 0))
    assert "/" not in name
    assert "\\" not in name
    assert ".." not in name
    assert name.endswith(".md")