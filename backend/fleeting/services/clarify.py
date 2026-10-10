"""#260 a clarifying question for vague captures.

A capture like "call John about the thing" is not wrong, it is under-specified
— and filing it as a task makes it untriable later, because you cannot act on
"the thing" a fortnight after writing it. So the pipeline holds the note back
and asks what was meant.

Detection is deliberately narrow and deterministic. A rule that flags half the
inbox is worse than no rule: the user learns to ignore the queue, and then the
one real question is invisible. Every verdict carries its reason for the same
reason #259's do — an unexplainable flag cannot be corrected.

The question comes from the model when one is available, because phrasing a
question is language work. There is a template when not, so a dead LLM never
blocks a capture.

The answer to the question is appended to the capture and the hold is lifted,
then re-enriched: answering must not silently lose the original words.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .writing import LLMUnavailable, _style_section

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.clarify")

# A reference that has nothing to refer to. Matched at the *start* of the
# capture or after a comma, never anywhere: "I fixed the bug and it works now"
# is a finished sentence, and flagging it would teach the user to ignore the
# queue. Same shape as the people index's soft-token rule.
_DANGLING_START = re.compile(r"^(?:please\s+|hey\s+|um\s+|uh\s+|so\s+)+(it|that|this)\b", re.IGNORECASE)
_VAGUE_NOUNS = ("the thing", "that thing", "the stuff", "stuff like that", "whatever")
_WORD = re.compile(r"[a-z0-9']+")

_DEFAULT_QUESTION = "What do you mean exactly — who or what is this about?"


def _tokens(text: str) -> list[str]:
    """Words, for scripts that space them; characters, for scripts that do not.

    CJK has no word boundaries, so `[a-z0-9']+` matches zero characters in a
    Chinese note and every one of them scored as "0 words and nothing to
    anchor them" — a fully specified Chinese capture held back as vague.
    Counting CJK characters as their own tokens keeps the minimum-word guard
    meaningful in both families. Still a rough count, but no longer a wrong one.
    """
    latin = _WORD.findall((text or "").lower())
    cjk = re.findall(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text or "")
    return latin + cjk


def is_vague(note: dict) -> tuple[bool, list[str]]:
    """(vague, reasons) for whether this capture can be acted on later.

    Narrow on purpose. Two signals, both of which mean the same thing — the
    words on their own do not name the thing being described:

    - a reference with nothing to refer to ("it", "call about the thing")
    - a content-free capture: fewer than four content words and no proper
      noun, name or date to anchor it
    """
    text = (note.get("raw_text") or "").strip()
    if not text:
        return False, []

    reasons: list[str] = []
    lowered = text.lower()

    if _DANGLING_START.match(text):
        reasons.append("starts with a reference with nothing to refer to")
    for noun in _VAGUE_NOUNS:
        if noun in lowered:
            reasons.append(f"contains '{noun}'")
            break

    tokens = _tokens(text)
    has_anchor = any(t[0].isupper() for t in re.findall(r"[A-Za-z][A-Za-z'\-]+", text)) or bool(
        re.search(r"\b(january|february|march|april|may|june|july|august|september|"
                  r"october|november|december|monday|tuesday|wednesday|thursday|"
                  r"friday|saturday|sunday|tomorrow|today)\b", lowered)
    )
    if len(tokens) < 4 and not has_anchor:
        reasons.append(f"only {len(tokens)} word(s) and nothing to anchor them")

    return bool(reasons), reasons


async def _ask(prompt_system: str, text: str, cfg: "Config") -> str:
    """One model call, or LLMUnavailable — the caller decides what that means."""
    from .llm import _post_chat, auth_headers, normalize_base_url

    if cfg.llm.provider == "none":
        raise LLMUnavailable("llm disabled")
    base = normalize_base_url(cfg.llm.base_url)
    if cfg.llm.provider in ("lmstudio", "custom"):
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": text},
            ],
            "temperature": 0.4,
            "max_tokens": 512,
        }
        url = f"{base}/v1/chat/completions"
    else:
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": text},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.4},
        }
        url = f"{base}/api/chat"
    content = await _post_chat(url, payload, cfg.llm.timeout_secs, auth_headers(cfg.llm))
    if not content.strip():
        raise LLMUnavailable("model returned an empty response")
    return content.strip()


async def clarifying_question(note: dict, cfg: "Config") -> str | None:
    """One question to ask about a vague capture, or None when it is clear."""
    vague, _ = is_vague(note)
    if not vague:
        return None
    system = (
        "You ask one short question about a note the user wrote, because it is "
        "too vague to act on later. Reply with the question only — no preamble, "
        "no explanation. Ask who or what it is about, never suggest content."
        + _style_section(getattr(cfg, "writing_style_guide", "") or "")
    )
    try:
        return await _ask(system, note.get("raw_text") or "", cfg)
    except LLMUnavailable:
        # A dead provider must never block a capture, and there is a question
        # worth asking even without a model.
        return _DEFAULT_QUESTION
    except Exception as exc:
        log.warning("clarifying question failed: %s", exc)
        return _DEFAULT_QUESTION


async def step(db: "Database", cfg: "Config", *, _note_id: str) -> str | None:
    """Hold a vague note back for review and record its question.

    Idempotent: a note already holding a question is not asked again, so a
    reprocess cannot overwrite an answer the user is halfway through typing.
    """
    note = db.get_note(_note_id)
    if not note or not (note.get("raw_text") or "").strip():
        return None
    fields = _fields_of(note)
    if fields.get("clarify"):
        return str(fields["clarify"])

    question = await clarifying_question(note, cfg)
    if not question:
        return None

    db.update_note(_note_id, {"review_state": "raw", "fields": {"clarify": question}})
    return question


def _fields_of(note: dict) -> dict[str, Any]:
    raw = note.get("fields")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def answer(db: "Database", note_id: str, reply: str) -> dict | None:
    """Record the user's answer, lift the hold, and keep their original words.

    The clarification is appended rather than replacing the capture, so
    answering cannot destroy what was written. The caller re-enriches.
    """
    note = db.get_note(note_id)
    if not note:
        return None
    reply = (reply or "").strip()
    if not reply:
        return None

    original = (note.get("raw_text") or "").strip()
    merged = f"{original}\n\n{reply}" if original else reply
    fields = _fields_of(note)
    fields.pop("clarify", None)

    return db.update_note(note_id, {"raw_text": merged, "fields": fields, "review_state": "enriched"})
