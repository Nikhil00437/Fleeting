"""#143: strip the reliably-identifiable things from a note, so it can be shared.

The failure mode of every redaction feature is the same — it produces output
that *looks* redacted, you send it, and someone finds the thing you were worried
about. So the rule is that a pattern is only redacted when matching it is
reliable, and everything unreliable is left alone and said out loud.

**Person names are not pattern-matched.** `Alice`, `Prof. Ng` and "my brother
Raj" are not separable from ordinary words by regex; a guessing pass mangles
notes while giving the comfortable impression that names were handled. The
caller supplies the names they know:

    POST /api/export {"redact": true, "names": ["Alice", "Bob"]}

That is honest — you know your own names and a regex does not — and the report
distinguishes "found nothing" from "looked for nothing".

Two details that are easy to get wrong:

- **No `.` in a pattern without `re.DOTALL`-intent.** A pattern that matches
  across a newline deletes everything between two unrelated lines.
- **Short digit runs are left alone.** A version, a percentage, a year, a PR
  number. Redacting those makes the export useless for the thing people
  actually export notes for, and the addresses that matter (cards, phones) are
  longer.
"""

from __future__ import annotations

import re

# Ordered: the specific patterns run before the general ones, so a card number
# is reported as `number` rather than being chewed up by something looser.
PATTERNS: dict[str, re.Pattern[str]] = {
    # The local part is bounded at 64 because that is RFC 5321's limit *and*
    # because an unbounded  on a long run of word characters is quadratic:
    # 200k of them took 130 seconds. The limit is the fix, not a workaround.
    "email": re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{2,63}"),
    "secret": re.compile(
        r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b|\bgh[pousr]_[A-Za-z0-9]{16,}\b|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
    ),
    # 13+ digits, optionally grouped by spaces or dashes. The lower bound is what
    # keeps `1.2.3`, `60%`, `2024` and `PR #4821` intact.
    "number": re.compile(r"(?<![\w.])(?:\d[ -]?){12,}\d(?![\w.])"),
    "phone": re.compile(r"(?<![\w.])\+?\d[\d ()-]{8,}\d(?![\w.])"),
    "url": re.compile(r"\bhttps?://[^\s<>\"')]+"),
}

_PLACEHOLDER = {
    "email": "[email]",
    "secret": "[secret]",
    "number": "[number]",
    "phone": "[phone]",
    "url": "[url]",
}


def _name_pattern(names: list[str]) -> re.Pattern[str] | None:
    """A caller-supplied name, matched on word boundaries.

    The boundary is the whole point: `Al` must not turn "Always" into
    "[person-1]ways". That is how a redactor destroys the document it was meant
    to protect, and it is invisible until someone reads the export.
    """
    cleaned = sorted({n.strip() for n in (names or []) if isinstance(n, str) and n.strip()}, key=len, reverse=True)
    if not cleaned:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(n) for n in cleaned) + r")(?!\w)", re.IGNORECASE)


def redact(text: str | None, names: list[str] | None = None) -> tuple[str, dict[str, int]]:
    """Return `(redacted_text, what_was_found)`.

    Idempotent: running it twice gives the same output, because the placeholders
    contain nothing a pattern matches. A pipeline that redacts on the way out
    and again on the way in must not disagree with itself.
    """
    if not text or not isinstance(text, str):
        return text or "", {}

    hits: dict[str, int] = {}
    out = text
    for label, pattern in PATTERNS.items():
        out, n = pattern.subn(_PLACEHOLDER[label], out)
        if n:
            hits[label] = n

    name_re = _name_pattern(names or [])
    if name_re is not None:
        counters: dict[str, str] = {}

        def swap(match: re.Match[str]) -> str:
            # Stable per distinct name: "Alice met Bob" reads as two people, not
            # the same one twice.
            key = match.group(0).lower()
            if key not in counters:
                counters[key] = f"[person-{len(counters) + 1}]"
            return counters[key]

        out, n = name_re.subn(swap, out)
        if n:
            hits["names"] = n
    return out, hits
