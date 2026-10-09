"""LLM enrichment via a local OpenAI-ish server (Ollama / LM Studio).

The enricher asks the local model to structure raw captures into
{title, summary, tags, action_items}. If the model is unreachable, times out,
or returns garbage, callers fall back to `heuristic_enrich` so the app keeps
working fully offline — capture must never fail because enrichment did.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import LLMConfig

log = logging.getLogger("fleeting.llm")

MAX_ENRICH_CHARS = 12_000

STOPWORDS = frozenset(
    """a an and are as at be but by for from get got has have he her his i if in
    into is it its just like me my no not of on or our so some than that the
    their them then there these they this to too up us was we were what when
    where which who why will with you your about really very much many also do
    does did doing done can could should would need wants want thing things
    stuff going gonna okay ok yeah yes""".split()
)

ENRICH_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "priority": {"type": "string", "enum": ["P1", "P2", "P3"]},
                    "due_date": {"type": "string"},
                    "repo": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    "required": ["title", "summary", "tags", "action_items"],
}

# #96: what the enrichment schema adds beyond the four required keys. Kept
# outside ENRICH_SCHEMA so the strict `required` list stays minimal — a model
# that must emit confidence will emit a confident-looking 1.0 whether or not
# the note is clear.
ENRICH_OPTIONAL_SCHEMA = {
    "confidence": {
        "type": "number",
        "description": (
            "How confident you are that this title, summary, tag set and task "
            "list are faithful to the note. 1.0 only when the note is "
            "unambiguous; below 0.5 when you had to guess or the note is a "
            "fragment."
        ),
    },
}

ENRICH_SYSTEM_TEMPLATE = (
    "Today's date is {today_iso}.\n"
    "You organize raw personal notes for a local note-taking app. "
    "You receive a captured note (possibly a messy voice transcript) and must respond "
    "with ONLY a JSON object with these keys:\n"
    '- "title": a short specific title, max 60 characters, no quotes around it\n'
    '- "summary": 1-3 sentence summary of the key content\n'
    '- "tags": 2-6 short lowercase topical tags (single words or-hyphenated), no "#" prefix\n'
    '- "action_items": array of concrete actionable tasks stated in the note. '
    'Each task is an object with:\n'
    '  - "text": short imperative sentence (e.g. \'Update the resume with ARIA deployment experience\')\n'
    '  - "priority": \'P1\' for urgent/blocker/asap/critical, \'P3\' for someday/low-priority, \'P2\' for normal\n'
    '  - "due_date": format as YYYY-MM-DD if mentioned (resolving \'tomorrow\', \'next monday\', etc. relative to today); null if not mentioned\n'
    '  - "repo": project or codebase name if referenced; null if not referenced\n'
    "Phrases like 'remember to …', 'need to …', 'have to …', 'todo: …' ARE action items — extract them. "
    "Empty array only if the note truly contains no task or intent to act. Do NOT invent tasks.\n"
    "Use the same language as the note.\n"
    'Also report "confidence": a number from 0 to 1 for how faithful your title, '
    "summary, tags and tasks are to the note. Use below 0.5 when you had to guess "
    "or the note is an unclear fragment — a low number is useful, an inflated one is not."
)

ENRICH_SYSTEM = ENRICH_SYSTEM_TEMPLATE.format(
    today_iso=date.today().isoformat()
)


class ActionItemDict(dict):
    """Dictionary representing an action item with backward compatibility for string equality."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.get("text") == other
        return super().__eq__(other)


class LLMUnavailable(Exception):
    """Raised when the local LLM cannot enrich a note."""


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def auth_headers(cfg: LLMConfig) -> dict[str, str]:
    """Authorization header for endpoints that need one.

    Sent whenever a key is configured, regardless of provider: local servers
    ignore it, and an OpenAI-compatible gateway may sit behind any of them.
    """
    key = (cfg.api_key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def chat_model_names(entries: list[dict], provider: str) -> list[str]:
    """Model names usable for chat, from a provider's /models listing.

    Ollama reports a `capabilities` list per model; embedding-only models must be
    excluded or the settings UI will happily offer one as the enrichment model
    and every capture silently falls back to heuristics. Older Ollama builds omit
    the field, so treat a missing list as chat-capable rather than hiding all.
    """
    if provider == "ollama":
        return [
            e.get("name")
            for e in entries
            if e.get("name")
            and "completion" in (e.get("capabilities") or ["completion"])
        ]
    return [e.get("id") for e in entries if e.get("id")]


async def check_llm(cfg: LLMConfig) -> dict:
    """Probe the configured LLM server; returns status info for the UI."""
    base = normalize_base_url(cfg.base_url)
    if cfg.provider == "none":
        return {"ok": False, "detail": "LLM disabled in settings"}
    try:
        async with httpx.AsyncClient(timeout=4, headers=auth_headers(cfg)) as client:
            if cfg.provider == "ollama":
                r = await client.get(f"{base}/api/tags")
                r.raise_for_status()
                entries = r.json().get("models", [])
            else:  # lmstudio / custom / openai-compatible
                r = await client.get(f"{base}/v1/models")
                r.raise_for_status()
                entries = r.json().get("data", [])
        models = chat_model_names(entries, cfg.provider)
        hidden = len(entries) - len(models)
        if not models:
            return {
                "ok": False,
                "detail": "server reachable but no chat models installed",
                "models": [],
                "hidden": hidden,
            }
        if cfg.model and cfg.model not in models and not any(m.startswith(cfg.model) for m in models):
            return {
                "ok": False,
                "detail": f"model '{cfg.model}' not found on server",
                "models": models,
                "hidden": hidden,
            }
        return {"ok": True, "models": models, "hidden": hidden}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "models": [], "hidden": 0}


async def _post_chat(url: str, payload: dict, timeout: float, headers: dict | None) -> str:
    """One HTTP round trip. Raises httpx errors for the chain to interpret."""
    async with httpx.AsyncClient(timeout=timeout, headers=headers or None) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return _extract_content(resp.json())


async def request_chat(
    url: str,
    payload: dict,
    timeout_secs: int,
    *,
    provider: str = "ollama",
    headers: dict[str, str] | None = None,
) -> str:
    """POST a chat request to an Ollama/OpenAI-compatible server, return content."""
    try:
        content = await _post_chat(url, payload, timeout_secs, headers)
    except Exception as exc:
        raise LLMUnavailable(f"request failed: {type(exc).__name__}: {exc}") from exc
    if not content.strip():
        raise LLMUnavailable("model returned an empty response")
    return content


PRIORITY_SYSTEM_PROMPT = (
    "You triage a to-do item. Reply with JSON only: "
    '{"priority": "P1"|"P2"|"P3"}. '
    "P1 = time-critical today or blocking someone; "
    "P2 = matters this week; P3 = whenever. "
    "Judge only urgency and consequence, never length or tone."
)


async def infer_priority(text: str, cfg: LLMConfig) -> str | None:
    """#31: ask the local model to rank a task. Returns None when it cannot.

    Deliberately raises nothing: an unavailable model must leave the task at
    P2, not fail the capture. Callers treat None as "no opinion".
    """
    if cfg.provider == "none" or not text.strip():
        return None
    base = normalize_base_url(cfg.base_url)
    snippet = text[:400]
    messages = [
        {"role": "system", "content": PRIORITY_SYSTEM_PROMPT},
        {"role": "user", "content": snippet},
    ]
    if cfg.provider in ("lmstudio", "custom"):
        payload: dict = {
            "model": cfg.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 32,
            "response_format": {"type": "json_object"},
        }
        url = f"{base}/v1/chat/completions"
    else:
        payload = {
            "model": cfg.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": '{"priority": "P1|P2|P3"}',
            "options": {"temperature": 0},
        }
        url = f"{base}/api/chat"
    try:
        content = await request_chat(
            url, payload, cfg.timeout_secs, provider=cfg.provider, headers=auth_headers(cfg)
        )
    except LLMUnavailable:
        return None
    parsed = _parse_json_loose(content) or {}
    value = str(parsed.get("priority", "")).strip().upper()
    return value if value in ("P1", "P2", "P3") else None


async def enrich(text: str, cfg: LLMConfig, prompt: str | None = None) -> dict:
    """Return {title, summary, tags, action_items} from the local LLM.

    #1: `prompt` carries the capture template's extra instruction, appended
    to the system prompt. Raises LLMUnavailable on any failure — fall back.
    """
    if cfg.provider == "none" or not text.strip():
        raise LLMUnavailable("llm disabled or empty text")

    base = normalize_base_url(cfg.base_url)
    snippet = text[:MAX_ENRICH_CHARS]

    today_iso = datetime.now(timezone.utc).date().isoformat()
    system_prompt = ENRICH_SYSTEM_TEMPLATE.format(today_iso=today_iso)
    if prompt:
        system_prompt += f"\n\nCapture-template instruction: {prompt}"

    if cfg.provider in ("lmstudio", "custom"):
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": snippet},
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
        }
        url = f"{base}/v1/chat/completions"
    else:  # ollama
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": snippet},
            ],
            "stream": False,
            "think": False,
            "format": {**ENRICH_SCHEMA, **ENRICH_OPTIONAL_SCHEMA},
            "options": {"temperature": 0.3},
        }
        url = f"{base}/api/chat"

    content = await request_chat(
        url, payload, cfg.timeout_secs, provider=cfg.provider, headers=auth_headers(cfg)
    )
    parsed = _parse_json_loose(content)
    if parsed is None:
        raise LLMUnavailable("model returned unparseable JSON")
    return _sanitize(parsed)


def model_chain(cfg: LLMConfig) -> list[str]:
    """#266: the models to try, in order, deduped. Empty when nothing is set."""
    models = [cfg.model.strip()] + [m.strip() for m in (cfg.fallback_models or "").split(",")]
    seen: list[str] = []
    for m in models:
        if m and m not in seen:
            seen.append(m)
    return seen


async def enrich_chain(
    text: str,
    cfg: LLMConfig,
    prompt: str | None = None,
    few_shot: str = "",
) -> dict:
    """#266: `enrich` across `model_chain`, then the caller's heuristic pass.

    Each step gets timeout_secs divided across the chain. Without that, a chain
    of three would let the first hanging model consume the entire budget and the
    other two would never actually get a turn — the fallback would be decorative.
    A step that returns unparseable JSON counts as a failed step, since a model
    that ignored the schema will not do better on the retry.
    """
    if cfg.provider == "none" or not text.strip():
        raise LLMUnavailable("llm disabled or empty text")

    models = model_chain(cfg)
    if not models:
        raise LLMUnavailable("no model configured")

    base = normalize_base_url(cfg.base_url)
    per_step = max(5.0, cfg.timeout_secs / len(models))
    headers = auth_headers(cfg)
    today_iso = datetime.now(timezone.utc).date().isoformat()
    base_prompt = ENRICH_SYSTEM_TEMPLATE.format(today_iso=today_iso)
    # #256: the user's own corrected enrichments, which outrank anything the
    # template can say about their taste.
    if few_shot:
        base_prompt += f"\n\n{few_shot}"
    if prompt:
        base_prompt += f"\n\nCapture-template instruction: {prompt}"

    last_error = "no attempt made"
    for model in models:
        if cfg.provider in ("lmstudio", "custom"):
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": base_prompt},
                    {"role": "user", "content": text[:MAX_ENRICH_CHARS]},
                ],
                "temperature": 0.3,
                "max_tokens": 1024,
                "response_format": {"type": "json_object"},
            }
            url = f"{base}/v1/chat/completions"
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": base_prompt},
                    {"role": "user", "content": text[:MAX_ENRICH_CHARS]},
                ],
                "stream": False,
                "think": False,
                "format": {**ENRICH_SCHEMA, **ENRICH_OPTIONAL_SCHEMA},
                "options": {"temperature": 0.3},
            }
            url = f"{base}/api/chat"

        try:
            content = await _post_chat(url, payload, per_step, headers)
            parsed = _parse_json_loose(content)
            if parsed is None:
                last_error = f"{model}: unparseable JSON"
                continue
            return _sanitize(parsed)
        except Exception as exc:
            last_error = f"{model}: {type(exc).__name__}: {exc}"

    raise LLMUnavailable(f"all models failed ({last_error})")


def _extract_content(data: dict) -> str:
    raw = ""
    if "message" in data and isinstance(data["message"], dict):  # ollama chat
        raw = data["message"].get("content") or ""
    elif "choices" in data and data["choices"]:  # openai-compatible
        raw = data["choices"][0].get("message", {}).get("content") or ""
    elif "response" in data:  # ollama generate
        raw = data.get("response") or ""
    # Strip any inline <think>...</think> blocks from reasoning models
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw


def _parse_json_loose(content: str) -> dict | None:
    content = content.strip()
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # strip markdown fences, then grab the outermost {...}
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE)
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass
    start, end = fenced.find("{"), fenced.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(fenced[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


PRIORITY_P1_RE = re.compile(r"\b(p1|urgent|critical|asap|blocker|immediately)\b", re.IGNORECASE)
PRIORITY_P3_RE = re.compile(r"\b(p3|someday|eventually|low[- ]priority)\b", re.IGNORECASE)

DUE_DATE_RE = re.compile(
    r"\b(?:by|due|before|on)\s+(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

REPO_RE = re.compile(
    r"\b(?:in|for)\s+([a-zA-Z0-9_-]+)\s+repo\b|\brepo:\s*([a-zA-Z0-9_-]+)\b|#([a-zA-Z0-9_-]+)\b",
    re.IGNORECASE,
)

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

REPO_STOPWORDS = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "it",
    "today", "tomorrow", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "now", "later", "soon", "work", "home",
})


def _extract_priority(line: str) -> str:
    if PRIORITY_P1_RE.search(line):
        return "P1"
    if PRIORITY_P3_RE.search(line):
        return "P3"
    return "P2"


def _resolve_due_date(match_str: str, today: date) -> str | None:
    token = match_str.lower()
    if token == "today":
        return today.isoformat()
    if token == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if token in WEEKDAYS:
        target = WEEKDAYS[token]
        days_ahead = (target - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (today + timedelta(days=days_ahead)).isoformat()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
        try:
            datetime.strptime(token, "%Y-%m-%d")
            return token
        except ValueError:
            return None
    return None


def _extract_repo(line: str) -> str | None:
    for m in REPO_RE.finditer(line):
        name = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
        if not name or name in REPO_STOPWORDS:
            continue
        return name
    return None


def _coerce_confidence(raw: object) -> float | None:
    """#96: accept a reported confidence or nothing at all.

    A number the app made up would look authoritative and mean nothing, so a
    non-numeric answer becomes None rather than a default. `True`/`False` are
    rejected explicitly — bool is an int subclass in Python, and `confidence:
    true` is a model misunderstanding, not a 100% certainty.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return min(1.0, max(0.0, value))


def _sanitize(parsed: dict) -> dict:
    title = str(parsed.get("title") or "").strip().strip('"').strip()
    summary = str(parsed.get("summary") or "").strip()
    raw_tags = parsed.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in re.split(r"[,;]", raw_tags) if t.strip()]
    tags = []
    for t in raw_tags:
        t = str(t).strip().lstrip("#").lower().replace(" ", "-")
        t = re.sub(r"[^a-z0-9\u0900-\u097F-]", "", t)
        if t and t not in tags:
            tags.append(t)
    tags = tags[:6]

    raw_items = parsed.get("action_items") or []
    if isinstance(raw_items, str):
        raw_items = [raw_items]
    elif not isinstance(raw_items, list):
        raw_items = []

    action_items = []
    for raw in raw_items:
        if isinstance(raw, str):
            text = raw.strip()
            priority = "P2"
            due_date = None
            repo = None
        elif isinstance(raw, dict):
            text = str(raw.get("text") or "").strip()
            raw_p = str(raw.get("priority") or "P2").strip().upper()
            priority = raw_p if raw_p in ("P1", "P2", "P3") else "P2"

            raw_due = raw.get("due_date")
            due_date = None
            if raw_due and isinstance(raw_due, str):
                raw_due = raw_due.strip()
                if re.match(r"^\d{4}-\d{2}-\d{2}$", raw_due):
                    try:
                        datetime.strptime(raw_due, "%Y-%m-%d")
                        due_date = raw_due
                    except ValueError:
                        due_date = None

            raw_repo = raw.get("repo")
            repo = None
            if raw_repo:
                r = str(raw_repo).strip().lower()
                r = re.sub(r"^(?:#|repo:)", "", r).strip()
                r = re.sub(r"[^a-z0-9_-]", "", r)
                repo = r if r else None
        else:
            continue

        if not text:
            continue

        action_items.append(
            ActionItemDict({
                "text": text[:200],
                "priority": priority,
                "due_date": due_date,
                "repo": repo,
            })
        )

    return {
        "title": title[:80],
        "summary": summary[:1200],
        "confidence": _coerce_confidence(parsed.get("confidence")),
        "tags": tags,
        "action_items": action_items[:10],
    }


# ---- offline fallback --------------------------------------------------


def heuristic_enrich(text: str, today: date | None = None) -> dict:
    """Structure a note without any model — decent titles, tags, TODO mining."""
    text = text.strip()
    if not text:
        return {
            "title": "Empty capture",
            "summary": "",
            "tags": [],
            "action_items": [],
            "confidence": None,
        }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    title = lines[0]
    # strip list markers / timestamps from title candidate
    title = re.sub(r"^\s*(?:[-*•\d]+[.)]?\s+|\[\d+:\d+\]\s*)+", "", title)
    title = title[:60].rstrip(" ,;:.!?-—") or "Untitled capture"

    body = " ".join(lines[1:]) or lines[0]
    sentences = re.split(r"(?<=[.!?])\s+", body)
    summary = ""
    for s in sentences[:4]:
        if len(summary) + len(s) > 320:
            break
        summary += (" " if summary else "") + s
    if not summary:
        summary = body[:320]

    words = re.findall(r"[a-zA-Z\u0900-\u097F][a-zA-Z\u0900-\u097F-]{2,}", text.lower())
    words = [w for w in words if w not in STOPWORDS]
    tags = [w for w, _ in Counter(words).most_common(5) if _]

    action_items = []
    if today is None:
        today = date.today()
    todo_re = re.compile(
        r"^(?:todo|task|fix|remember|call|email|mail|buy|send|ask|review|write|finish|"
        r"deploy|ship|check|read|watch|book|pay|schedule|prep(?:are)?|follow[ -]up)\b[,: ]+(.{4,})",
        re.IGNORECASE,
    )
    for line in lines:
        raw_item_text = None
        m = todo_re.match(line)
        if m:
            raw_item_text = m.group(1).strip().rstrip(".")[:140]
        elif re.match(r"^[-*•]\s*\[ \]", line):
            raw_item_text = re.sub(r"^[-*•]\s*\[ \]\s*", "", line)[:140]
        elif line.lower().startswith("todo:") or "need to " in line.lower() or "have to " in line.lower():
            raw_item_text = line[:140]

        if not raw_item_text:
            continue

        priority = _extract_priority(line)

        due_date = None
        due_m = DUE_DATE_RE.search(line)
        if due_m:
            due_date = _resolve_due_date(due_m.group(1), today)

        repo = _extract_repo(line)

        action_items.append(
            ActionItemDict({
                "text": raw_item_text,
                "priority": priority,
                "due_date": due_date,
                "repo": repo,
            })
        )

    # de-dup, cap
    seen = set()
    deduped = []
    for a in action_items:
        txt = a["text"]
        if txt not in seen:
            seen.add(txt)
            deduped.append(a)
    action_items = deduped[:10]

    # #96: deterministic extraction is not *uncertain*, it simply is not a
    # model. Reporting a confidence here would be a fabricated number.
    return {
        "title": title,
        "summary": summary,
        "tags": tags[:5],
        "action_items": action_items,
        "confidence": None,
    }


async def stream_chat(
    url: str,
    payload: dict,
    timeout_secs: int,
    *,
    provider: str = "ollama",
    headers: dict[str, str] | None = None,
):
    """Async generator of content deltas from a streaming chat request.

    Yields str chunks; raises LLMUnavailable on failure. Handles both Ollama
    NDJSON and OpenAI-compatible SSE (LM Studio) framing.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout_secs, headers=headers or None) as client:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if provider == "lmstudio":
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            return
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        delta = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                            or ""
                        )
                    else:
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = (data.get("message") or {}).get("content") or ""
                        if data.get("done"):
                            if delta:
                                yield delta
                            return
                    if delta:
                        yield delta
    except Exception as exc:
        raise LLMUnavailable(f"request failed: {type(exc).__name__}: {exc}") from exc
