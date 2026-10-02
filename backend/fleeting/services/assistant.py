"""Grounded RAG assistant engine for "Ask Fleeting".

Synthesizes multi-source context (hybrid-searched notes, relational tasks, daily activity logs)
to answer user questions with citations, supporting both local LLMs and offline extractive fallback.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from .llm import LLMUnavailable, normalize_base_url, request_chat
from .semantic_search import hybrid_search

if TYPE_CHECKING:
    from ..config import Config
    from ..db import Database

log = logging.getLogger("fleeting.assistant")

LOG_KEYWORDS = ("today", "yesterday", "week", "work", "activity", "log", "summary")

CHAT_STOPWORDS = frozenset(
    """a an and are as at be but by for from get got has have he her his how i if in
    into is it its just like me my no not of on or our so some than that the
    their them then there these they this to too up us was we were what when
    where which who why will with you your about really very much many also do
    does did doing done can could should would need wants want thing things
    stuff going gonna okay ok yeah yes tell explain show find give please""".split()
)


def _extract_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_\-#]+", query)
    return [t for t in tokens if t.lower() not in CHAT_STOPWORDS]


def build_assistant_context(
    query: str,
    db: Database,
    cfg: Config,
    *,
    repo: str | None = None,
    filter_type: str | None = None,
) -> tuple[str, list[dict], dict]:
    """Retrieve relevant notes, active tasks, and recent daily logs to build grounded assistant context.

    Returns:
        (context_text, sources, context_used_counts)
    """
    clean_query = (query or "").strip()

    # 1. Notes via hybrid search
    notes: list[dict] = []
    if clean_query:
        try:
            notes = hybrid_search(
                db,
                clean_query,
                cfg,
                mode="hybrid",
                limit=5,
                repo=repo,
                filter_type=filter_type,
            )
            # If conversational natural language query returned no notes, try extracted keywords
            if not notes:
                keywords = _extract_keywords(clean_query)
                if keywords:
                    kw_phrase = " ".join(keywords)
                    if kw_phrase.lower() != clean_query.lower():
                        notes = hybrid_search(
                            db,
                            kw_phrase,
                            cfg,
                            mode="hybrid",
                            limit=5,
                            repo=repo,
                            filter_type=filter_type,
                        )
                # If still no notes, try searching individual significant keywords
                if not notes and keywords:
                    for kw in keywords:
                        if len(kw) >= 4:
                            notes = hybrid_search(
                                db,
                                kw,
                                cfg,
                                mode="hybrid",
                                limit=5,
                                repo=repo,
                                filter_type=filter_type,
                            )
                            if notes:
                                break
        except Exception as exc:
            log.warning("Hybrid search failed in assistant context: %s", exc)
            notes = []

    # 2. Open tasks
    tasks: list[dict] = []
    try:
        if repo:
            tasks = db.list_tasks(status="open", repo=repo, limit=6)
        else:
            if clean_query:
                matching = db.list_tasks(status="open", q=clean_query, limit=6)
                if not matching:
                    keywords = _extract_keywords(clean_query)
                    for kw in keywords:
                        if len(kw) >= 3:
                            matching = db.list_tasks(status="open", q=kw, limit=6)
                            if matching:
                                break
                if matching:
                    tasks = matching
                else:
                    tasks = db.list_tasks(status="open", limit=6)
            else:
                tasks = db.list_tasks(status="open", limit=6)
    except Exception as exc:
        log.warning("Task retrieval failed in assistant context: %s", exc)
        tasks = []

    # 3. Daily logs if query mentions time/activity/summary
    logs: list[dict] = []
    query_tokens = set(re.findall(r"\b[a-zA-Z0-9_\-#]+\b", clean_query.lower()))
    if any(kw in query_tokens for kw in LOG_KEYWORDS):
        try:
            cursor = db.execute("SELECT day, summary_md FROM daily_logs ORDER BY day DESC LIMIT 2")
            logs = [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            log.warning("Daily logs retrieval failed in assistant context: %s", exc)
            logs = []

    # 4. Build structured sources list
    sources: list[dict] = []
    for n in notes:
        snippet = n.get("snippet") or n.get("summary") or ""
        sources.append({
            "id": str(n["id"]),
            "title": str(n.get("title") or "Untitled"),
            "type": str(n.get("type") or "note"),
            "kind": "note",
            "snippet": str(snippet).strip(),
        })

    for t in tasks:
        snippet = f"Priority {t.get('priority', 'P2')}"
        if t.get("due_date"):
            snippet += f", Due {t['due_date']}"
        sources.append({
            "id": str(t["id"]),
            "title": str(t.get("text") or "Untitled Task"),
            "type": "task",
            "kind": "task",
            "snippet": snippet,
        })

    for l in logs:
        day_str = str(l.get("day", ""))
        snippet = (l.get("summary_md") or "").strip()[:160]
        sources.append({
            "id": day_str,
            "title": f"Daily Log ({day_str})",
            "type": "log",
            "kind": "log",
            "snippet": snippet,
        })

    # 5. Assemble formatted context sections
    sections: list[str] = []

    if notes:
        lines = ["=== Relevant Notes ==="]
        for n in notes:
            note_id = n.get("id")
            title = n.get("title") or "Untitled"
            ntype = n.get("type") or "note"
            tags = ", ".join(n.get("tags") or [])
            header = f"- [[note:{note_id}|{title}]] (type: {ntype}" + (f", tags: {tags}" if tags else "") + ")"
            lines.append(header)
            summary = (n.get("summary") or "").strip()
            if summary:
                lines.append(f"  Summary: {summary}")
            snip = (n.get("snippet") or (n.get("raw_text") or "")[:200]).strip()
            if snip and snip != summary:
                lines.append(f"  Content: {snip}")
        sections.append("\n".join(lines))

    if tasks:
        lines = ["=== Active Tasks ==="]
        for t in tasks:
            tid = t.get("id")
            text = t.get("text") or ""
            pri = t.get("priority") or "P2"
            details = []
            if t.get("repo"):
                details.append(f"repo: {t['repo']}")
            if t.get("due_date"):
                details.append(f"due: {t['due_date']}")
            detail_str = f" ({', '.join(details)})" if details else ""
            lines.append(f"- [[task:{tid}|{text}]] [Priority: {pri}]{detail_str}")
        sections.append("\n".join(lines))

    if logs:
        lines = ["=== Recent Activity Logs ==="]
        for l in logs:
            day = l.get("day", "")
            summary = (l.get("summary_md") or "").strip()
            lines.append(f"- Day {day}:\n{summary}")
        sections.append("\n".join(lines))

    context_text = "\n\n".join(sections)
    context_used = {
        "notes_count": len(notes),
        "tasks_count": len(tasks),
        "logs_count": len(logs),
    }

    return context_text, sources, context_used


def _extractive_heuristic_answer(query: str, context_text: str, sources: list[dict]) -> str:
    """Fast offline fallback when no LLM is available.

    Summarizes top matched notes and open tasks with structured citations
    [[note:id|title]] and [[task:id|text]].
    """
    if not sources:
        return "I couldn't find any relevant notes or tasks in memory matching your question."

    notes = [s for s in sources if s.get("kind") == "note"]
    tasks = [s for s in sources if s.get("kind") == "task"]
    logs = [s for s in sources if s.get("kind") == "log"]

    q_lower = query.lower()
    asking_tasks = any(w in q_lower for w in ("task", "todo", "action", "due", "priority", "p1", "p2", "p3"))
    asking_logs = any(w in q_lower for w in ("today", "yesterday", "week", "work", "activity", "log", "summary"))

    sections: list[str] = []

    if asking_tasks and tasks:
        sections.append("Here are the relevant active tasks:")
        for t in tasks:
            meta = f" ({t['snippet']})" if t.get("snippet") else ""
            sections.append(f"- [[task:{t['id']}|{t['title']}]]{meta}")
        if notes:
            sections.append("\nRelated notes:")
            for n in notes:
                desc = f": {n['snippet']}" if n.get("snippet") else ""
                sections.append(f"- [[note:{n['id']}|{n['title']}]]{desc}")
    elif asking_logs and logs:
        sections.append("Here is your recent activity summary:")
        for l in logs:
            sections.append(f"- Daily Log {l['id']}:\n  {l.get('snippet', '')}")
        if tasks:
            sections.append("\nActive tasks:")
            for t in tasks:
                meta = f" ({t['snippet']})" if t.get("snippet") else ""
                sections.append(f"- [[task:{t['id']}|{t['title']}]]{meta}")
    else:
        if notes:
            sections.append("Here are the most relevant notes:")
            for n in notes:
                desc = f": {n['snippet']}" if n.get("snippet") else ""
                sections.append(f"- [[note:{n['id']}|{n['title']}]]{desc}")
        if tasks:
            prefix = "\nActive tasks:" if notes else "Active tasks:"
            sections.append(prefix)
            for t in tasks:
                meta = f" ({t['snippet']})" if t.get("snippet") else ""
                sections.append(f"- [[task:{t['id']}|{t['title']}]]{meta}")
        if logs and not notes and not tasks:
            sections.append("Recent activity logs:")
            for l in logs:
                sections.append(f"- Daily Log {l['id']}: {l.get('snippet', '')}")

    return "\n".join(sections)


async def ask_assistant(
    messages: list[dict],
    db: Database,
    cfg: Config,
    *,
    repo: str | None = None,
    filter_type: str | None = None,
) -> dict:
    """Orchestrate grounded RAG assistant response with source citations."""
    user_query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_query = str(m.get("content") or "").strip()
            break

    if not user_query:
        return {
            "message": {"role": "assistant", "content": "How can I help you today?"},
            "sources": [],
            "context_used": {"notes_count": 0, "tasks_count": 0, "logs_count": 0},
        }

    context_text, sources, context_used = build_assistant_context(
        user_query, db, cfg, repo=repo, filter_type=filter_type
    )

    if cfg.llm.provider != "none":
        system_prompt = (
            "You are 'Ask Fleeting', a personal knowledge assistant built into Fleeting.\n"
            "You answer user questions using only their personal captured notes, tasks, and activity logs provided in the context below.\n\n"
            "Instructions:\n"
            "1. Answer clearly, concisely, and directly based on the provided context.\n"
            "2. Ground your answers strictly in the context. Do not invent information not supported by the context.\n"
            "3. Cite your sources using exact double-bracket links:\n"
            "   - For notes: [[note:NOTE_ID|Title]]\n"
            "   - For tasks: [[task:TASK_ID|Task text]]\n"
            "4. If the context does not contain enough information to answer the question, state that clearly and suggest what the user might search for.\n\n"
            f"Context:\n{context_text}"
        )
        base = normalize_base_url(cfg.llm.base_url)
        dialogue = [m for m in messages if m.get("role") != "system"]
        full_messages = [
            {"role": "system", "content": system_prompt},
            *dialogue,
        ]
        if cfg.llm.provider == "lmstudio":
            payload = {
                "model": cfg.llm.model,
                "messages": full_messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            }
            url = f"{base}/v1/chat/completions"
        else:  # ollama
            payload = {
                "model": cfg.llm.model,
                "messages": full_messages,
                "stream": False,
                "think": False,
                "options": {"temperature": 0.3},
            }
            url = f"{base}/api/chat"

        try:
            content = await request_chat(url, payload, cfg.llm.timeout_secs, provider=cfg.llm.provider)
        except (LLMUnavailable, Exception) as exc:
            log.warning("Assistant LLM request failed, falling back to extractive answer: %s", exc)
            content = _extractive_heuristic_answer(user_query, context_text, sources)
    else:
        content = _extractive_heuristic_answer(user_query, context_text, sources)

    return {
        "message": {"role": "assistant", "content": content},
        "sources": sources,
        "context_used": context_used,
    }


def get_assistant_suggestions(db: Database, cfg: Config) -> list[str]:
    """Generate 3-5 dynamic prompt suggestions based on DB state."""
    suggestions: list[str] = []

    try:
        p1_tasks = db.list_tasks(status="open", priority="P1", limit=1)
        if p1_tasks:
            suggestions.append("What urgent P1 tasks do I have?")

        due_today = db.list_tasks(status="open", due="today", limit=1)
        if due_today:
            suggestions.append("What tasks are due today?")
        else:
            overdue = db.list_tasks(status="open", due="overdue", limit=1)
            if overdue:
                suggestions.append("What overdue tasks do I need to complete?")

        open_tasks = db.list_tasks(status="open", limit=1)
        if open_tasks and len(suggestions) < 2:
            suggestions.append("What are my highest priority open tasks?")

        log_row = db.execute("SELECT day FROM daily_logs ORDER BY day DESC LIMIT 1").fetchone()
        if log_row:
            suggestions.append("What did I work on recently?")

        tags = db.all_tags()
        if tags:
            top_tag = tags[0].get("tag")
            if top_tag:
                clean_tag = str(top_tag).lstrip("#")
                suggestions.append(f"Summarize notes tagged with #{clean_tag}")

        notes = db.list_notes(limit=1)
        if notes and len(suggestions) < 3:
            suggestions.append("Summarize my recent notes")
    except Exception as exc:
        log.warning("Error generating suggestions from DB: %s", exc)

    defaults = [
        "What urgent tasks need my attention?",
        "Summarize my recent notes",
        "What did I work on today?",
        "What action items are pending across my projects?",
    ]

    for d in defaults:
        if d not in suggestions:
            suggestions.append(d)
        if len(suggestions) >= 4:
            break

    return suggestions[:5]
