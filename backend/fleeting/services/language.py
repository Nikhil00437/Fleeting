"""#262 the note's own language, detected from its script.

Not a model call: detecting a language is pattern matching, and the model is
the slowest and least reliable way to do it. Script detection is also coarse on
purpose — it separates CJK from Latin from Cyrillic from Arabic and calls a
mixed note by its dominant script. It is a script detector wearing a language
detector's name, and `Language.name` says what it actually measured.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Ranges, not a dependency. Unicode block boundaries are stable and the ones
# here are the ones that matter for notes.
_SCRIPTS: tuple[tuple[str, str, tuple[tuple[int, int], ...]], ...] = (
    ("ja", "Japanese", ((0x3040, 0x309F), (0x30A0, 0x30FF))),
    ("zh", "Chinese", ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))),
    ("ko", "Korean", ((0xAC00, 0xD7AF), (0x1100, 0x11FF), (0x3130, 0x318F))),
    ("ru", "Russian", ((0x0400, 0x04FF),)),
    ("ar", "Arabic", ((0x0600, 0x06FF), (0x0750, 0x077F))),
    ("he", "Hebrew", ((0x0590, 0x05FF),)),
    ("hi", "Devanagari", ((0x0900, 0x097F),)),
    ("th", "Thai", ((0x0E00, 0x0E7F),)),
    ("el", "Greek", ((0x0370, 0x03FF),)),
)

# Kana settles Japanese against Chinese: the two share Han characters, and a
# note containing kana is Japanese however many Han characters surround it.
_KANA = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")

# A name the user typed in Latin inside a CJK note must not flip the answer,
# so Latin letters are counted but capped below any real CJK content.
_LATIN = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    confidence: float

    @property
    def known(self) -> bool:
        return self.code != "und"


UNKNOWN = Language(code="und", name="Unknown", confidence=0.0)


def _script_of(char: str) -> str | None:
    point = ord(char)
    for code, _name, ranges in _SCRIPTS:
        if any(low <= point <= high for low, high in ranges):
            return code
    return None


def detect_language(text: str) -> Language:
    """The dominant script of `text`, as a language.

    Empty in, Unknown out. Defaulting to English would put "write in English"
    into every note that said nothing, which is the opposite of what the setting
    is for.
    """
    counts: dict[str, int] = {}
    latin = other_letters = 0
    for char in (text or ""):
        if not char.strip():
            continue
        code = _script_of(char)
        if code:
            counts[code] = counts.get(code, 0) + 1
        elif unicodedata.category(char).startswith("L"):
            if _LATIN.match(char):
                latin += 1
            else:
                other_letters += 1

    if not counts and latin == 0 and other_letters == 0:
        return UNKNOWN

    total = sum(counts.values()) + latin + other_letters
    if total == 0:
        return UNKNOWN

    # Kana anywhere means Japanese; Han alone cannot tell zh from ja.
    if _KANA.search(text or "") and counts.get("ja", 0) + counts.get("zh", 0):
        ja = counts.get("ja", 0)
        han = counts.get("zh", 0)
        return Language("ja", "Japanese", round((ja + han) / total, 3))

    if not counts:
        return Language("en", "English", round(latin / total, 3)) if latin else UNKNOWN

    best = max(counts, key=lambda c: counts[c])
    names = {code: name for code, name, _ in _SCRIPTS}
    return Language(best, names.get(best, best), round(counts[best] / total, 3))


_INSTRUCTIONS = {
    "zh": "Write the title, summary and action items in Chinese, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "ja": "Write the title, summary and action items in Japanese, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "ko": "Write the title, summary and action items in Korean, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "ru": "Write the title, summary and action items in Russian, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "ar": "Write the title, summary and action items in Arabic, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "he": "Write the title, summary and action items in Hebrew, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "hi": "Write the title, summary and action items in Hindi, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "th": "Write the title, summary and action items in Thai, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
    "el": "Write the title, summary and action items in Greek, matching the note. "
          "Leave names, brands, paths and identifiers exactly as they appear.",
}


def language_instruction(language: Language) -> str:
    """The prompt line for a detected language, or "" when there is nothing to say.

    English is absent on purpose — the prompt is already English, so telling the
    model to answer in English says only what it already knows.
    """
    return _INSTRUCTIONS.get(language.code, "")


def detect_code(text: str) -> str:
    return detect_language(text).code