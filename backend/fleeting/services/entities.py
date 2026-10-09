"""#411 people index, #412 last mentioned, #416 stale contacts.

Deterministic extraction over stored notes. This is deliberately crude: a
capitalised run is not a person, and the stoplist below is the list of ways
that is wrong. The alternative — an LLM pass per note — is neither free at
capture time nor correctable afterwards, and #414's alias merging only works
against something you can inspect and edit.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database

# One to three capitalised tokens, allowing internal hyphens, capitalised
# apostrophes ("O'Brien") and trailing initials ("Ben C."). The apostrophe must
# be followed by a capital, which is what keeps "Priya's" from being captured
# with its possessive. The initial alternative exists because "Ben C." and "Ben"
# are different people and conflating them is invisible and irreversible.
_NAME_TOKEN = r"(?:[A-Z](?:[a-z\-]+|['’][A-Z][a-z\-]*)\b|[A-Z]\.)"
# The lookbehind rejects camelCase: a capital preceded by a lowercase letter is
# inside a word, not starting a name. Without it "GitHub" yields "Hub" and
# "OpenAI" yields "I" — and no stoplist can enumerate every product name.
_NAME_RE = re.compile(rf"(?<![a-z])({_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,2}})")

# Function words and other tokens that can never appear *inside* a name. A run
# containing any of these is rejected outright: "The bridge network" is not a
# person called "The bridge network".
HARD_STOP = frozenset("""
the a an and or but if then when while after before during
this that these those there here what which who whom whose why how
monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october november december
today tomorrow yesterday tonight later now next last
i we you he she they me my our your their his her him them us
note notes todo todos task tasks inbox capture reminder summary
github gitlab docker kubernetes python javascript typescript react rust golang
openai anthropic ollama vscode jetbrains slack notion linear
""".split())

# Sentence-initial verbs. These are only ever wrong at the *front* of a run —
# "Ask Priya" is Priya — so they are stripped rather than rejecting the run.
# Stripping rather than rejecting is the whole reason this is a second list.
SOFT_LEADING_STOP = frozenset("""
shipped met ask asked sent fixed added removed updated created deleted
opened closed started finished reviewed merged deployed pushed pulled
please thanks thank ok okay yes no
""".split())


def extract_people(text: str) -> list[str]:
    """Capitalised runs that survive the stoplists, in first-seen order.

    Two rules, and the difference matters. A hard token anywhere in the run
    kills it, because no name contains "the". A soft token only kills the run
    when it leads, so "Ask Priya" still yields Priya while "Ask the team"
    yields nothing.
    """
    out: list[str] = []
    for match in _NAME_RE.finditer(text or ""):
        tokens = match.group(1).split()
        if tokens and tokens[0].lower() in SOFT_LEADING_STOP:
            tokens = tokens[1:]
        if not tokens or any(t.lower() in HARD_STOP for t in tokens):
            continue
        name = " ".join(tokens)
        if len(name) < 3 or name in out:
            continue
        out.append(name)
    return out


def count_people(text: str) -> dict[str, int]:
    """Occurrences per person in one text — "Priya and Priya" is two mentions.

    Distinct from `extract_people`, which dedupes: a person list must not
    repeat someone, but a mention count should.
    """
    counts: dict[str, int] = {}
    for match in _NAME_RE.finditer(text or ""):
        tokens = match.group(1).split()
        if tokens and tokens[0].lower() in SOFT_LEADING_STOP:
            tokens = tokens[1:]
        if not tokens or any(t.lower() in HARD_STOP for t in tokens):
            continue
        name = " ".join(tokens)
        if len(name) >= 3:
            counts[name] = counts.get(name, 0) + 1
    return counts


def mention_counts(db: Database) -> dict[str, int]:
    """Total mentions per person across non-trashed, non-sensitive notes."""
    counts: dict[str, int] = {}
    rows = db.execute(
        "SELECT raw_text FROM notes WHERE trashed_at IS NULL AND sensitive = 0"
    ).fetchall()
    for row in rows:
        for name, n in count_people(row["raw_text"] or "").items():
            counts[name] = counts.get(name, 0) + n
    return counts


def _canonical(db: Database, name: str, aliases: dict[str, str]) -> str:
    """Resolve `name` through user-stated aliases (#414), preserving case."""
    target = aliases.get(name.lower())
    if not target:
        return name
    # Prefer the canonical's own spelling as it appears in the notes, so a
    # merged row reads "Ben" and not "ben".
    for row in db.execute(
        "SELECT DISTINCT raw_text FROM notes WHERE trashed_at IS NULL AND sensitive = 0"
    ).fetchall():
        for candidate in extract_people(row["raw_text"] or ""):
            if candidate.lower() == target.lower() and candidate[0].isupper():
                return candidate
    return target


def people_index(db: Database) -> list[dict]:
    """People with a mention count and first/last seen dates.

    Deliberately not filtered on `status`: a note pending enrichment still has
    a real body, and its author is still mentioned in it.

    #412 and #416 both read this one query: "last mentioned" and "who have I
    not talked to in a while" are the same column, filtered differently. #414
    folds aliases in here, so no caller has to remember to.
    """
    rows = db.execute(
        """
        SELECT raw_text, created_at FROM notes
        WHERE trashed_at IS NULL AND sensitive = 0
        ORDER BY created_at
        """
    ).fetchall()

    aliases = db.alias_map("person")
    agg: dict[str, dict] = {}
    for row in rows:
        day = (row["created_at"] or "")[:10]
        for name, n in count_people(row["raw_text"] or "").items():
            key = _canonical(db, name, aliases)
            entry = agg.setdefault(
                key,
                {"name": key, "mentions": 0, "notes_count": 0,
                 "first_seen": day, "last_seen": day},
            )
            entry["mentions"] += n
            entry["notes_count"] += 1
            if day:
                entry["first_seen"] = min(filter(None, (entry["first_seen"], day)))
                entry["last_seen"] = max(filter(None, (entry["last_seen"], day)))

    return sorted(agg.values(), key=lambda p: (-p["mentions"], p["name"].lower()))


def ambiguous_first_names(db: Database) -> list[dict]:
    """#417: first names shared by more than one person in the index.

    Reported, never resolved. Two real people called Ben is the normal case,
    not an error, so guessing which one a note means would corrupt the index
    in a way nobody can see afterwards.
    """
    by_first: dict[str, set[str]] = {}
    for person in people_index(db):
        first = person["name"].split()[0]
        by_first.setdefault(first, set()).add(person["name"])
    return [
        {"first_name": first, "names": sorted(names)}
        for first, names in sorted(by_first.items())
        if len(names) > 1
    ]


def resolve_ambiguity(db: Database, alias: str, canonical: str) -> bool:
    """#417: the user says which Ben a note meant. Just an alias, recorded."""
    known = {p["name"].lower() for p in people_index(db)}
    if canonical.strip().lower() not in known:
        return False
    return db.record_entity_alias(alias, canonical)


def stale_people(db: Database, days: int, *, today: date | None = None) -> list[dict]:
    """#416: people whose last mention is older than `days`.

    `days <= 0` means the feature is off and the answer is always empty — the
    idea says opt-in, and a stale-contact list nobody asked for is noise.

    Ordered longest silence first, because that is the one worth acting on. A
    contact with no usable date is skipped rather than guessed at.
    """
    if days <= 0:
        return []
    now = today or date.today()
    cutoff = (now - timedelta(days=days)).isoformat()
    out = [p for p in people_index(db) if p.get("last_seen") and p["last_seen"] < cutoff]
    return sorted(out, key=lambda p: (p["last_seen"], p["name"].lower()))


def notes_for_person(db: Database, name: str) -> list[dict]:
    """#413: every note mentioning `name`, newest first.

    Goes through `get_note` rather than reusing the scan's row dicts: that is
    the single note deserializer, and a raw `SELECT *` row is not a note.
    """
    rows = db.execute(
        """
        SELECT id, raw_text FROM notes
        WHERE trashed_at IS NULL AND sensitive = 0
        ORDER BY created_at DESC
        """
    ).fetchall()
    out = []
    aliases = db.alias_map("person")
    # A canonical name reaches its aliases' notes too, or a merged person
    # would lose half their history on their own page.
    wanted = {name.lower()} | {
        a for a, c in aliases.items() if c.lower() == name.lower()
    }
    for row in rows:
        found = {n.lower() for n in extract_people(row["raw_text"] or "")}
        if found & wanted:
            note = db.get_note(row["id"])
            if note:
                out.append(note)
    return out
