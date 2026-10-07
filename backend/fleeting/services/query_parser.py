"""One query parser for FTS, the web UI and the future MCP server.

Every search surface (FTS SQL, hybrid search, saved queries) shares this
module instead of building its own SQL strings — operator syntax lands once
(#313, #318) and behaves identically everywhere.

Grammar (operators case-insensitive, tokens whitespace-separated):

    word             plain term, prefix-matched
    "a phrase"       exact phrase
    -word            exclusion (also -"a phrase")
    tag:name         note must carry the tag (``#`` stripped, AND across tags)
    type:voice       note type filter (repeatable, OR)
    before:DATE      created strictly before that UTC day (exclusive)
    after:DATE       created on or after that UTC day (inclusive)
    is:starred       starred notes only
    has:audio        notes with audio attached
    near:N           the two preceding terms/phrases must occur within N
                     tokens of each other (FTS5 NEAR)

Unknown ``foo:bar`` tokens degrade to plain terms and invalid dates are
dropped: a typo'd operator must never silently empty a query. Dates are
UTC-day semantics on purpose — keyword and semantic legs must agree on what
"before" means, and both compare ``created_at`` strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NEAR_RE = re.compile(r"^near:(\d+)$", re.IGNORECASE)
_TOKEN_RE = re.compile(r'"([^"]*)"|(\S+)')
_MAX_NEAR = 50


def _is_valid_day(value: str) -> bool:
    return bool(_DATE_RE.match(value)) and _date_ok(value)


def _date_ok(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _clean_word(token: str) -> str:
    """Same character policy the FTS builder always used (alnum, ``-``, ``_``)."""
    return "".join(ch for ch in token if ch.isalnum() or ch in "-_")


def _clean_phrase(phrase: str) -> str:
    # Double quotes inside a phrase would terminate the FTS string early.
    return phrase.replace('"', " ").strip()


@dataclass
class ParsedQuery:
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    excluded_phrases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    before: str | None = None
    after: str | None = None
    starred: bool = False
    has_audio: bool = False
    # (unit_a, unit_b, distance) — the two preceding text units, not the raw
    # tokens, so `"wireless setup" "router" near:3` groups phrase + term.
    near: tuple[str, str, int] | None = None
    # Everything the embedder should see: terms, phrases and NEAR members in
    # query order, operators stripped.
    _text_units: list[str] = field(default_factory=list, repr=False)

    @property
    def has_positive(self) -> bool:
        """True when there is something to rank (FTS can produce a MATCH)."""
        return bool(self.terms or self.phrases or self.near)

    @property
    def has_constraints(self) -> bool:
        """True when the query narrows the corpus at all (exclusions and
        filters count — ``-draft`` alone is a valid query, not an empty one)."""
        return bool(
            self.has_positive
            or self.excluded
            or self.excluded_phrases
            or self.tags
            or self.types
            or self.before
            or self.after
            or self.starred
            or self.has_audio
        )

    def free_text(self) -> str:
        return " ".join(self._text_units).strip()


def parse_query(raw: str) -> ParsedQuery:
    p = ParsedQuery()
    if not raw or not raw.strip():
        return p

    units: list[tuple[str, str]] = []  # ("term"|"phrase", text) pending for NEAR
    pending = _TOKEN_RE.findall(raw)
    i = 0
    while i < len(pending):
        quoted, plain = pending[i]
        i += 1

        if quoted:
            phrase = _clean_phrase(quoted)
            if phrase:
                p.phrases.append(phrase)
                units.append(("phrase", phrase))
                p._text_units.append(phrase)
            continue

        token = plain.strip()
        if not token:
            continue
        lowered = token.lower()

        # Exclusions: leading dash (double dash tolerated). Internal dashes
        # are word characters — "state-of-mind" is a term, "-draft" is not.
        stripped = token.lstrip("-")
        if stripped and stripped != token and not lowered.startswith("---"):
            if token.startswith('-"'):
                # -"a phrase" — the regex split the quoted part off; glue the
                # tokens back together up to the closing quote.
                phrase, i = _rejoin_excluded_phrase(pending, i - 1)
                if phrase:
                    p.excluded_phrases.append(phrase)
                continue
            word = _clean_word(stripped)
            if word:
                p.excluded.append(word)
            continue

        if lowered.startswith("tag:") and len(token) > 4:
            tag = token[4:].strip().lstrip("#").strip()
            if tag:
                p.tags.append(tag.lower())
            continue

        if lowered.startswith("type:") and len(token) > 5:
            value = _clean_word(token[5:]).lower()
            if value:
                p.types.append(value)
            continue

        if lowered.startswith("before:") or lowered.startswith("after:"):
            op, value = lowered.split(":", 1)
            if _is_valid_day(value):
                if op == "before":
                    p.before = value
                else:
                    p.after = value
            # Invalid dates are dropped, not turned into terms: a date the
            # user meant to filter by must not become a BM25 noise token.
            continue

        if lowered in ("is:starred", "is:star"):
            p.starred = True
            continue

        if lowered in ("has:audio", "is:audio"):
            p.has_audio = True
            continue

        near_m = _NEAR_RE.match(token)
        if near_m:
            distance = min(int(near_m.group(1)), _MAX_NEAR) or 1
            if len(units) >= 2:
                a_kind, a_text = units[-2]
                b_kind, b_text = units[-1]
                # Remove exactly one occurrence of each grouped unit — the
                # same word may also appear elsewhere in the query.
                _remove_last(p.terms if a_kind == "term" else p.phrases, a_text)
                _remove_last(p.terms if b_kind == "term" else p.phrases, b_text)
                p.near = (a_text, b_text, distance)
                units = units[:-2]
            # With fewer than two preceding units there is nothing to group;
            # treat it as a plain term rather than dropping user text.
            else:
                word = _clean_word(token)
                if word:
                    p.terms.append(word)
                    units.append(("term", word))
                    p._text_units.append(word)
            continue

        word = _clean_word(token)
        if word:
            p.terms.append(word)
            units.append(("term", word))
            p._text_units.append(word)

    return p


def _remove_last(lst: list[str], value: str) -> None:
    """Remove the last occurrence of value (NEAR consumes the two units it
    groups; earlier duplicates stay as independent terms)."""
    for j in range(len(lst) - 1, -1, -1):
        if lst[j] == value:
            del lst[j]
            return


def _rejoin_excluded_phrase(
    pending: list[tuple[str, str]], dash_idx: int
) -> tuple[str, int]:
    """Reassemble the quoted text after a leading ``-"`` token.

    ``-"a phrase"`` tokenizes as ``-"a`` + ``phrase"``; glue everything from
    the dash token up to the one closing the quote. Returns the phrase text
    (without the dash/quotes — possibly empty) and the index of the first
    token after the consumed span.
    """
    joined = ""
    idx = dash_idx
    while idx < len(pending):
        quoted, plain = pending[idx]
        idx += 1
        if joined:
            # The tokenizer split at the whitespace; rejoin with one space.
            joined += " "
        if quoted:
            joined += quoted
            break
        joined += plain
        if plain.endswith('"'):
            break
    if not joined.startswith('-"'):
        return "", idx
    return _clean_phrase(joined[2:].rstrip('"')), idx


def build_fts_match(p: ParsedQuery) -> str | None:
    """FTS5 MATCH string for the text part of the query, or None when the
    query has no positive text units (callers fall back to a filtered scan).

    Terms are prefix queries, phrases are exact, exclusions become a NOT
    group. The positive half is parenthesised whenever NOT is present — FTS5
    binds juxtaposition tighter than NOT, but explicit parens keep the intent
    obvious and survive future operator additions.
    """
    units: list[str] = [f'"{t}"*' for t in p.terms]
    units += [f'"{ph}"' for ph in p.phrases]
    if p.near:
        a, b, n = p.near
        units.append(f'NEAR("{a}" "{b}", {n})')
    if not units:
        return None

    positive = " ".join(units)
    neg_units = [f'"{w}"*' for w in p.excluded] + [f'"{ph}"' for ph in p.excluded_phrases]
    if not neg_units:
        return positive
    return f"({positive}) NOT ({' OR '.join(neg_units)})"


def filter_conditions(p: ParsedQuery, alias: str = "n") -> tuple[list[str], dict]:
    """SQL WHERE fragments for the structured operators (tag/type/date/
    audio/starred). Column-alias aware so both the FTS-joined scan and the
    plain notes scan can use them."""
    conds: list[str] = []
    params: dict = {}

    if p.types:
        placeholders = ", ".join(f":type{i}" for i in range(len(p.types)))
        conds.append(f"{alias}.type IN ({placeholders})")
        for i, t in enumerate(p.types):
            params[f"type{i}"] = t

    for i, tag in enumerate(p.tags):
        # Tags are stored with or without a leading '#' depending on where
        # the capture came from — match either, like tagTree does.
        conds.append(
            f"EXISTS (SELECT 1 FROM json_each({alias}.tags) je "
            f"WHERE REPLACE(LOWER(je.value), '#', '') = :tag{i})"
        )
        params[f"tag{i}"] = tag

    if p.before:
        conds.append(f"{alias}.created_at < :before")
        params["before"] = p.before
    if p.after:
        conds.append(f"{alias}.created_at >= :after")
        params["after"] = p.after
    if p.starred:
        conds.append(f"{alias}.starred = 1")
    if p.has_audio:
        conds.append(f"({alias}.audio_path IS NOT NULL AND {alias}.audio_path != '')")

    return conds, params


def exclusion_conditions(p: ParsedQuery, alias: str = "n") -> tuple[list[str], dict]:
    """LIKE-based exclusions for the non-FTS scan path (no MATCH to attach a
    NOT group to). Substring semantics, same as the FTS NOT group gives on
    tokenised text."""
    conds: list[str] = []
    params: dict = {}
    blob = (
        f"LOWER(COALESCE({alias}.title, '') || ' ' || COALESCE({alias}.summary, '') "
        f"|| ' ' || COALESCE({alias}.raw_text, ''))"
    )
    for i, word in enumerate((*p.excluded, *p.excluded_phrases)):
        # '_' survives _clean_word and is a LIKE wildcard.
        escaped = word.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(f"{blob} NOT LIKE :excl{i} ESCAPE '\\'")
        params[f"excl{i}"] = f"%{escaped}%"
    return conds, params


def note_matches_parsed(note: dict, p: ParsedQuery) -> bool:
    """Python-side evaluation of the structured operators, for candidate sets
    that did not come out of the filtered SQL (semantic mode scores every
    embedded note and must apply the same filter the SQL leg applied)."""
    if p.types:
        note_type = str(note.get("type") or "").strip().lower()
        if note_type not in p.types:
            return False

    if p.tags:
        note_tags = {str(t).strip().lower().lstrip("#") for t in (note.get("tags") or [])}
        if not all(tag in note_tags for tag in p.tags):
            return False

    created = str(note.get("created_at") or "")
    day = created[:10]
    if p.before and (not day or day >= p.before):
        return False
    if p.after and (not day or day < p.after):
        return False

    if p.starred and not note.get("starred"):
        return False
    if p.has_audio and not str(note.get("audio_path") or "").strip():
        return False

    if p.excluded or p.excluded_phrases:
        blob = " ".join(
            str(note.get(k) or "") for k in ("title", "summary", "raw_text")
        ).lower()
        for word in (*p.excluded, *p.excluded_phrases):
            if word.lower() in blob:
                return False

    return True
