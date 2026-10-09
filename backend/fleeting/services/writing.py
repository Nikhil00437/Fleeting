"""#446 rewrite menu, #447 alternative titles, #451 style guide.

The prompt-injection rule is the reason this module exists in its current
shape: note bodies are untrusted text, so the thing being rewritten always
travels in the *user* turn. The style guide is a user setting, so it may go
in the system prompt — it is not attacker-controlled.

Every failure path degrades to "no suggestion" rather than raising, because a
menu that throws is worse than a menu that is briefly empty.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from . import llm as llm_svc
from .llm import LLMUnavailable

if TYPE_CHECKING:
    from ..config import LLMConfig

log = logging.getLogger("fleeting.writing")

# #446: the menu is a fixed list rather than free text. An LLM given the
# option to invent a style will invent one, and the caller then has to decide
# whether to honour it.
REWRITE_STYLES: tuple[str, ...] = ("shorter", "clearer", "friendlier", "more formal")

_STYLE_BRIEF = {
    "shorter": "Cut it to roughly half the length. Drop throat-clearing, keep every fact.",
    "clearer": "Same content, easier to read. Prefer short sentences and concrete words.",
    "friendlier": "Warmer and more conversational, without becoming casual or vague.",
    "more formal": "Professional register. Remove contractions and slang.",
}

REWRITE_SYSTEM = (
    "You rewrite the user's own text. Reply with the rewritten text only — no "
    "preamble, no explanation, no quotes around it. Preserve every fact, name, "
    "number and link from the original; a rewrite may not add information."
)

TITLE_SYSTEM = (
    "You suggest alternative titles for a captured note. Reply with JSON only: "
    '{"titles": ["...", "...", "..."]}. Give exactly three, each under 60 '
    "characters, each a different angle rather than a synonym. Never repeat "
    "the title the user already has."
)

STYLE_GUIDE_HEADER = "The user's style guide, which every output must follow:"


def _style_section(style_guide: str | None) -> str:
    guide = (style_guide or "").strip()
    return f"\n\n{STYLE_GUIDE_HEADER}\n{guide}" if guide else ""


def _system(style: str, style_guide: str | None) -> str:
    return REWRITE_SYSTEM + f"\n\nRewrite style — {style}: {_STYLE_BRIEF[style]}" + _style_section(style_guide)


async def _ask(
    system: str, user: str, cfg: LLMConfig, *, schema: dict | None = None
) -> str:
    """One chat call. Raises LLMUnavailable — callers decide what that means."""
    if cfg.provider == "none":
        raise LLMUnavailable("llm disabled")
    base = llm_svc.normalize_base_url(cfg.base_url)
    if cfg.provider in ("lmstudio", "custom"):
        payload: dict = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.4,
            "max_tokens": 1024,
        }
        if schema:
            payload["response_format"] = {"type": "json_object"}
        url = f"{base}/v1/chat/completions"
    else:
        payload = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.4},
        }
        if schema:
            payload["format"] = schema
        url = f"{base}/api/chat"
    content = await llm_svc._post_chat(url, payload, cfg.timeout_secs, llm_svc.auth_headers(cfg))
    if not content.strip():
        raise LLMUnavailable("model returned an empty response")
    return content


async def rewrite(text: str, style: str, cfg: LLMConfig, *, style_guide: str | None = None) -> str:
    """#446: rewrite `text` in one of `REWRITE_STYLES`.

    Raises ValueError for an unknown style rather than passing it through —
    the caller picks from a menu, so an unknown value is a bug, and guessing
    would quietly produce something the user never asked for.
    """
    if style not in REWRITE_STYLES:
        raise ValueError(f"unknown rewrite style: {style}")
    if not text or not text.strip():
        raise ValueError("nothing to rewrite")
    out = await _ask(_system(style, style_guide), text, cfg)
    return out.strip()


def _parse_titles(raw: str, current: str | None) -> list[str]:
    parsed = llm_svc._parse_json_loose(raw)
    if isinstance(parsed, dict):
        items = parsed.get("titles") or []
    elif isinstance(parsed, list):
        items = parsed
    else:
        return []
    if not isinstance(items, list):
        return []

    seen = {(current or "").strip().lower()}
    out: list[str] = []
    for item in items:
        title = str(item or "").strip()[:120]
        key = title.lower()
        if not title or key in seen:
            continue
        seen.add(key)
        out.append(title)
    return out


async def suggest_titles(
    text: str,
    cfg: LLMConfig,
    *,
    style_guide: str | None = None,
    current_title: str | None = None,
) -> list[str]:
    """#447: up to three alternative titles.

    Returns [] on any failure. A menu that raises is worse than a menu that is
    briefly empty, and a bad title is worse than no title.
    """
    if cfg.provider == "none" or not text or not text.strip():
        return []
    system = TITLE_SYSTEM + _style_section(style_guide)
    try:
        raw = await _ask(system, text, cfg, schema=TITLE_SCHEMA)
    except Exception as exc:
        log.info("title suggestions unavailable: %s", exc)
        return []
    return _parse_titles(raw, current_title)


TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        }
    },
    "required": ["titles"],
}
