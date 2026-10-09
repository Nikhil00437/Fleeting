"""#93 editable prompt templates for enrichment and reports.

The trap here is not storage, it is substitution. These templates go through
`str.format`, so a stray `{}` or an unclosed brace in a user's prompt would
raise at generation time — turning a typo in settings into a broken daily
report for every day after. `substitute` therefore never uses `str.format`
at all: it replaces the known placeholders and leaves every other brace
exactly as the user typed it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database

log = logging.getLogger("fleeting.prompt_templates")

TARGETS = ("enrich", "daily_report")

MAX_TEMPLATE_CHARS = 20_000

# Which placeholders each target understands. Kept explicit so an unknown
# target cannot accidentally be handed a substitution table.
PLACEHOLDERS: dict[str, dict[str, str]] = {
    "enrich": {"today_iso": "{today_iso}"},
    "daily_report": {"date": "{date}"},
}

_KV_PREFIX = "prompt_template:"


def _default_text(target: str) -> str:
    if target == "enrich":
        from .llm import ENRICH_SYSTEM_TEMPLATE

        return ENRICH_SYSTEM_TEMPLATE
    if target == "daily_report":
        from .dailylog import DAILY_LOG_SYSTEM

        return DAILY_LOG_SYSTEM
    raise ValueError(f"unknown prompt target: {target}")


def default_template(target: str) -> str:
    """The shipped prompt, unedited. Also what reset restores."""
    return _default_text(target)


def _check(target: str) -> None:
    if target not in TARGETS:
        raise ValueError(f"unknown prompt target: {target}")


def get_template(db: Database, target: str) -> tuple[str, dict]:
    """(text, meta). Falls back to the shipped default, never to nothing."""
    _check(target)
    saved = db.kv_get(f"{_KV_PREFIX}{target}")
    if saved and saved.strip():
        return saved, {"target": target, "is_default": False, "default_text": _default_text(target)}
    return _default_text(target), {
        "target": target,
        "is_default": True,
        "default_text": _default_text(target),
    }


def is_default(db: Database, target: str) -> bool:
    _check(target)
    return not (db.kv_get(f"{_KV_PREFIX}{target}") or "").strip()


def set_template(db: Database, target: str, body: str) -> dict:
    _check(target)
    text = (body or "").strip()
    if not text:
        raise ValueError("a prompt template cannot be empty")
    db.kv_set(f"{_KV_PREFIX}{target}", text[:MAX_TEMPLATE_CHARS])
    return {"target": target, "is_default": False}


def reset_template(db: Database, target: str) -> dict:
    _check(target)
    db.kv_set(f"{_KV_PREFIX}{target}", "")
    return {"target": target, "is_default": True}


def substitute(text: str, target: str, **values: str) -> str:
    """Fill the known placeholders, leave every other brace alone.

    Deliberately not `str.format`. A user prompt containing `{}`, `{0}` or an
    unclosed `{` would raise KeyError/ValueError here, and the failure would
    surface as a broken report or a failed capture rather than as a typo in
    settings.
    """
    out = text or ""
    for key in PLACEHOLDERS.get(target, {}):
        if key in values:
            out = out.replace(PLACEHOLDERS[target][key], str(values[key]))
    return out


def template_for(db: Database, target: str, **values: str) -> str:
    """The effective, substituted prompt for this call."""
    text, _meta = get_template(db, target)
    return substitute(text, target, **values)
