"""Daily log generation: synthesize raw window sessions, project files, git commits,
and captured notes into an actionable, high-signal daily work & memory digest.

The local LLM (Ollama / LM Studio) writes the digest; if it's unavailable a
smart deterministic synthesis is produced instead (merging focus blocks,
extracting window topics, and summarizing project files/commits/tasks without
noisy 0-minute switches or redundant app tables).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from ..activity import aggregate_day
from ..config import Config, expand_path
from ..db import Database

log = logging.getLogger("fleeting.dailylog")

MAX_TRANSCRIPT_CHARS = 14_000

BROWSER_SUFFIX_RE = re.compile(
    r"\s*[-—–]\s*(?:Google Chrome|Chromium|Brave|Mozilla Firefox|Zen Browser|ZCode|Visual Studio Code)\s*$",
    re.IGNORECASE,
)


def fmt_secs(seconds: int) -> str:
    if seconds < 60:
        return f"{max(1, int(seconds))}s" if seconds > 0 else "0m"
    m = int(seconds // 60)
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h {m % 60:02d}m"


def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return "??:??"


def clean_window_title(title: str, app_class: str = "") -> str:
    """Strip redundant browser/IDE suffixes and noise from window titles."""
    t = (title or "").strip()
    if not t or t == "(no title)":
        return ""
    t = BROWSER_SUFFIX_RE.sub("", t).strip()
    if t.lower() == app_class.lower():
        return ""
    return t


def merge_focus_blocks(sessions: list[dict]) -> list[dict]:
    """Merge fragmented window polls into meaningful focus blocks with distinct topics.

    Consecutive sessions in the same app (or separated by brief <30s alt-tabs) are
    folded together, and micro-switches (<45s) are filtered out unless nothing else exists.
    """
    if not sessions:
        return []

    ordered = sorted(sessions, key=lambda s: s["first_seen"])
    raw_blocks: list[dict] = []

    for s in ordered:
        secs = int(s.get("seconds") or 0)
        app = s["app_class"]
        title = clean_window_title(s.get("title") or "", app)
        first = s["first_seen"]
        last = s["last_seen"]

        # Ignore 0-second polls when merging if we already have blocks
        if secs <= 0 and raw_blocks:
            continue

        if raw_blocks and raw_blocks[-1]["app"] == app:
            blk = raw_blocks[-1]
            blk["last_seen"] = last
            blk["seconds"] += secs
            if title:
                blk["titles"][title] = blk["titles"].get(title, 0) + max(secs, 1)
        elif (
            len(raw_blocks) >= 2
            and secs < 25
            and raw_blocks[-1]["seconds"] < 25
        ):
            # Absorb tiny alt-tab noise into the preceding block
            raw_blocks[-1]["last_seen"] = last
            raw_blocks[-1]["seconds"] += secs
        else:
            titles_map = {title: max(secs, 1)} if title else {}
            raw_blocks.append(
                {
                    "app": app,
                    "first_seen": first,
                    "last_seen": last,
                    "seconds": secs,
                    "titles": titles_map,
                }
            )

    # Second pass: merge blocks of the same app separated by a tiny interruption
    merged: list[dict] = []
    for blk in raw_blocks:
        if merged and merged[-1]["app"] == blk["app"]:
            prev = merged[-1]
            prev["last_seen"] = blk["last_seen"]
            prev["seconds"] += blk["seconds"]
            for t, v in blk["titles"].items():
                prev["titles"][t] = prev["titles"].get(t, 0) + v
        else:
            merged.append(blk)

    # Filter out trivial <45s blocks if substantive blocks exist
    substantive = [b for b in merged if b["seconds"] >= 45]
    chosen = substantive if substantive else [b for b in merged if b["seconds"] > 0] or merged[:5]

    out: list[dict] = []
    for b in chosen:
        top_titles = [
            t
            for t, _ in sorted(b["titles"].items(), key=lambda kv: -kv[1])
            if t
        ][:3]
        out.append(
            {
                "app": b["app"],
                "first_hhmm": _hhmm(b["first_seen"]),
                "last_hhmm": _hhmm(b["last_seen"]),
                "seconds": b["seconds"],
                "topics": top_titles,
            }
        )
    return out


def _parse_ts(raw: str) -> datetime | None:
    """Parse a stored ISO timestamp into an aware datetime (assume UTC if naive)."""
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def collect_notes_context(db: Database, since: datetime, until: datetime) -> list[dict]:
    """Fetch captures created in [since, until], both ends inclusive.

    `notes.created_at` is UTC while `since`/`until` are local, so this compares
    parsed instants — string comparison silently shifted the window by the UTC
    offset and dropped notes from the digest.
    """
    if since.tzinfo is None:
        since = since.astimezone()
    if until.tzinfo is None:
        until = until.astimezone()
    try:
        notes = db.list_notes(limit=1000)
    except Exception:
        log.exception("daily log: could not read notes for the window")
        return []
    matched = []
    for n in notes:
        created = _parse_ts(n.get("created_at") or "")
        if created is not None and since <= created <= until:
            matched.append(n)
    return matched


def render_notes_context(notes: list[dict]) -> str:
    if not notes:
        return "Captured notes in Fleeting during this window: none."
    lines = [f"Captured notes & tasks in Fleeting ({len(notes)} captures):"]
    for n in notes[:12]:
        title = n.get("title") or "Untitled"
        ntype = n.get("type") or "text"
        summary = (n.get("summary") or n.get("raw_text") or "")[:160].replace("\n", " ")
        tags = ", ".join(f"#{t}" for t in (n.get("tags") or [])[:4])
        lines.append(f"- [{ntype}] {title} {f'({tags})' if tags else ''}: {summary}")
        for it in n.get("action_items") or []:
            status = "done" if it.get("done") else "OPEN TASK"
            lines.append(f"    · [{status}] {it.get('text')}")
    return "\n".join(lines)


def build_transcript(sessions: list[dict], max_chars: int = MAX_TRANSCRIPT_CHARS) -> str:
    """Compact, high-signal textual view of one day's activity for the LLM."""
    agg = aggregate_day(sessions)
    total = agg["total_seconds"]
    lines = [f"Total tracked active time: {fmt_secs(total)} across {len(agg['apps'])} apps.", ""]

    lines.append("Time per app & top active window titles:")
    for a in agg["apps"]:
        if a["seconds"] < 15 and total >= 120:
            continue
        pct = (a["seconds"] / total * 100) if total else 0
        lines.append(f"- {a['app']}: {fmt_secs(a['seconds'])} ({pct:.0f}%)")
        for t in a["titles"][:5]:
            cleaned = clean_window_title(t["title"], a["app"])
            if cleaned:
                lines.append(f"    · {cleaned} ({fmt_secs(t['seconds'])})")
    lines.append("")

    # #334 the user's own words about a stretch come before our guess about it.
    annotated = [s for s in sessions if (s.get("note") or "").strip()]
    if annotated:
        lines.append("What you said you were doing:")
        for s in sorted(annotated, key=lambda x: x["first_seen"]):
            lines.append(
                f"- [{s['first_seen'][11:16]}] {s['note']} "
                f"({fmt_secs(s.get('seconds') or 0)}, {s['app_class']})"
            )
        lines.append("")

    blocks = merge_focus_blocks(sessions)
    lines.append("Merged focus blocks (chronological, micro-switches removed):")
    for b in blocks[:25]:
        topics = f" — {'; '.join(b['topics'])}" if b["topics"] else ""
        lines.append(
            f"- [{b['first_hhmm']}–{b['last_hhmm']}] ({fmt_secs(b['seconds'])}) {b['app']}{topics}"
        )

    transcript = "\n".join(lines)
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars]
    return transcript


DAILY_LOG_SYSTEM = (
    "You are an insightful personal engineering & productivity assistant writing a high-signal "
    "Daily Digest from a user's local workspace telemetry: merged window focus blocks, "
    "window titles, modified project files, git commits, and notes/tasks captured in Fleeting.\n\n"
    "STRICT RULES:\n"
    "1. DO NOT output a '| App | Time | % |' markdown table (the UI already renders charts for app time).\n"
    "2. DO NOT output a raw list of 0m/1m timestamps or bare app names like '09:47–09:47 (0m) — zcode'.\n"
    "3. Focus on WHAT the user actually built, researched, read, and captured — synthesize window titles, "
    "modified project files, git commits, and captured notes into meaningful narrative bullets.\n"
    "4. Respond with clean Markdown ONLY using these exact sections:\n\n"
    "# Daily Digest — {date}\n\n"
    "## Executive Summary\n"
    "2–3 crisp sentences summarizing the main themes of the day, key projects worked on, and total deep-focus time.\n\n"
    "## Shipped & Active Projects\n"
    "Bulleted synthesis of concrete project/code/document work grounded in modified files, git commits, and IDE sessions. "
    "Name specific projects, file counts/types, and what was built or changed.\n\n"
    "## Deep Focus & Research\n"
    "3–6 bullets grouping the main focus sessions and web/research topics (mentioning specific window titles/topics and durations, never 0m noise).\n\n"
    "## Captured Notes & Next Steps\n"
    "Bullets highlighting any Fleeting notes/tasks captured today and concrete loose ends worth resuming next. "
    "Keep the entire digest under 320 words and never invent facts not in the input."
)


def build_effective_prompt(
    day: str,
    *,
    tone: str = "balanced",
    highlights_only: bool = False,
    questions_for_tomorrow: bool = False,
    custom_sections: list[dict] | None = None,
    prompt_override: str | None = None,
    db: Database | None = None,
) -> str:
    """Build the full LLM system prompt combining defaults and user overrides.

    `db` is optional so every existing caller is unchanged; with it, the base
    prompt is the user's edited template (#93) rather than the shipped one.
    The per-run `prompt_override` (#348) still composes on top — a saved
    template and a one-off instruction are different things.
    """
    base = DAILY_LOG_SYSTEM
    if db is not None:
        from .prompt_templates import template_for

        base = template_for(db, "daily_report", date=day)
    system_prompt = base.replace("{date}", day)
    if prompt_override and prompt_override.strip():
        system_prompt += f"\n\nAdditional user instructions:\n{prompt_override.strip()}"
    if tone != "balanced":
        system_prompt += f"\n\nTone preference: {tone}."
    if highlights_only:
        system_prompt += "\n\nFormat restriction: Produce top accomplishments and highlights only."
    if questions_for_tomorrow:
        system_prompt += "\n\nInclude a final '## Questions for Tomorrow' section with 2–3 thought-provoking questions for resuming work."
    if custom_sections:
        custom_titles = ", ".join(s.get("title", "") for s in custom_sections if s.get("title"))
        system_prompt += f"\n\nIn addition to standard sections, include these custom sections: {custom_titles}."
    return system_prompt


async def generate_with_llm(
    transcript: str,
    day: str,
    cfg,
    *,
    tone: str = "balanced",
    length: str = "medium",
    highlights_only: bool = False,
    questions_for_tomorrow: bool = False,
    custom_sections: list[dict] | None = None,
    prompt_override: str | None = None,
) -> tuple[str, str]:
    """Returns (markdown, model_used). Raises LLMUnavailable."""
    from ..services import llm as llm_svc

    if cfg.llm.provider == "none":
        raise llm_svc.LLMUnavailable("llm disabled")

    max_tokens = 1400
    if length == "short":
        max_tokens = 700
    elif length == "long":
        max_tokens = 2800

    system_prompt = build_effective_prompt(
        day,
        tone=tone,
        highlights_only=highlights_only,
        questions_for_tomorrow=questions_for_tomorrow,
        custom_sections=custom_sections,
        prompt_override=prompt_override,
    )

    base = cfg.llm.base_url.rstrip("/")
    # #92: reports get their own model — usually the larger one.
    model = llm_svc.model_for(cfg.llm, "report")
    if cfg.llm.provider == "lmstudio":
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            "temperature": 0.35,
            "max_tokens": max_tokens,
        }
        url = f"{base}/v1/chat/completions"
    else:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.35, "num_predict": max_tokens},
        }
        url = f"{base}/api/chat"

    content = await llm_svc.request_chat(
        url,
        payload,
        cfg.llm.timeout_secs,
        provider=cfg.llm.provider,
        headers=llm_svc.auth_headers(cfg.llm),
    )
    md = content.strip()
    if not md or len(md) < 40:
        raise llm_svc.LLMUnavailable("model returned an empty daily log")
    md = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", md, flags=re.MULTILINE).strip()
    return md, model or "local"


def fallback_digest(
    sessions: list[dict],
    day: str,
    *,
    scan: dict | None = None,
    git: list[dict] | None = None,
    notes: list[dict] | None = None,
    tone: str = "balanced",
    length: str = "medium",
    highlights_only: bool = False,
    questions_for_tomorrow: bool = False,
    custom_sections: list[dict] | None = None,
) -> str:
    """Smart deterministic synthesis when no LLM is available (no raw 0m spam or redundant tables)."""
    agg = aggregate_day(sessions)
    total = agg["total_seconds"]
    lines = [f"# Daily Digest — {day}", ""]
    if total == 0 and not (scan and scan.get("total")):
        lines += ["## Executive Summary", "", "No tracked activity recorded in this window."]
        return "\n".join(lines)

    top_apps = [a for a in agg["apps"] if a["seconds"] >= 60] or agg["apps"][:3]
    top_summary = ", ".join(
        f"**{a['app']}** ({fmt_secs(a['seconds'])})" for a in top_apps[:3]
    )
    files_total = (scan or {}).get("total", 0)
    files_phrase = (
        f" and touched **{files_total} files** across **{len((scan or {}).get('groups', []))} projects**"
        if files_total
        else ""
    )

    if tone == "standup":
        lines += ["## Completed", ""]
        if git or (scan and scan.get("groups")):
            for repo in (git or [])[:3]:
                lines.append(f"- Git ({repo['repo']}): {'; '.join(repo['subjects'][:3])}")
            for g in (scan or {}).get("groups", [])[:3]:
                lines.append(f"- Files in {g['label']}: modified {g['count']} files")
        if notes:
            for n in notes:
                for it in (n.get("action_items") or []):
                    if it.get("done"):
                        lines.append(f"- Done: {it.get('text')}")
        if not (git or (scan and scan.get("groups")) or notes):
            lines.append(f"- Active focus in {top_summary}")

        lines += ["", "## In Flight", ""]
        lines.append(f"- Working on main projects ({fmt_secs(total)} total focus time across {len(agg['apps'])} apps)")
        blocks = merge_focus_blocks(sessions)
        for b in blocks[:5]:
            topics = f" — *{', '.join(b['topics'])}*" if b["topics"] else ""
            lines.append(f"- **{b['app']}** ({fmt_secs(b['seconds'])}){topics}")

        lines += ["", "## Blockers & Next Steps", ""]
        has_blocker = False
        if notes:
            for n in notes:
                for it in (n.get("action_items") or []):
                    if not it.get("done"):
                        lines.append(f"- Todo: {it.get('text')}")
                        has_blocker = True
        if not has_blocker:
            lines.append("- No immediate blockers identified.")

    elif highlights_only:
        lines += ["## Top Accomplishments & Highlights", ""]
        lines.append(
            f"Logged **{fmt_secs(total)}** of active focus across {len(agg['apps'])} applications "
            f"(led by {top_summary}){files_phrase}."
        )
        if git:
            for repo in git[:3]:
                lines.append(f"- Shipped git commits in **{repo['repo']}**: {'; '.join(repo['subjects'][:2])}")
        if scan and scan.get("groups"):
            for g in scan.get("groups", [])[:3]:
                lines.append(f"- Significant progress in **{g['label']}** ({g['count']} files modified)")
        if notes:
            for n in notes[:3]:
                lines.append(f"- Captured **{n.get('title') or 'note'}**")

    else:
        lines += ["## Executive Summary", ""]
        lines.append(
            f"Logged **{fmt_secs(total)}** of active focus across {len(agg['apps'])} applications "
            f"(led by {top_summary}){files_phrase}."
        )

        # Shipped & Active Projects (if files or git exist)
        if (scan and scan.get("groups")) or git:
            lines += ["", "## Shipped & Active Projects", ""]
            for g in (scan or {}).get("groups", [])[:5]:
                exts = ", ".join(f"`{ext}`×{n}" for ext, n in g["exts"][:3])
                sample = g["samples"][0] if g.get("samples") else ""
                lines.append(
                    f"- **{g['label']}** — {g['count']} modified {'file' if g['count'] == 1 else 'files'} "
                    f"({exts}){f' · e.g. `{sample}`' if sample else ''}"
                )
            for repo in (git or [])[:4]:
                commits = "; ".join(repo["subjects"][:3])
                lines.append(f"- **Git ({repo['repo']})** — {commits}")

        # Deep Focus & Research Blocks (merged, no 0m spam)
        blocks = merge_focus_blocks(sessions)
        if blocks:
            lines += ["", "## Deep Focus & Research", ""]
            for b in blocks[:10]:
                topics = (
                    f" — *{', '.join(b['topics'])}*"
                    if b["topics"]
                    else ""
                )
                lines.append(
                    f"- **{b['first_hhmm']}–{b['last_hhmm']}** ({fmt_secs(b['seconds'])}) · **{b['app']}**{topics}"
                )

        # Captured Notes & Open Tasks
        if notes:
            lines += ["", "## Captured Notes & Next Steps", ""]
            for n in notes[:6]:
                title = n.get("title") or "Untitled capture"
                lines.append(f"- **[{n.get('type', 'note')}]** {title}")
                for it in (n.get("action_items") or []):
                    if not it.get("done"):
                        lines.append(f"  - Todo: {it.get('text')}")

    # Custom sections
    if custom_sections:
        for sec in custom_sections:
            sec_title = sec.get("title", "Custom Section")
            lines += ["", f"## {sec_title}", ""]
            matched_sessions = [s for s in sessions if sec_title.lower() in (s.get("app_class") or "").lower() or sec_title.lower() in (s.get("title") or "").lower()]
            if matched_sessions:
                for s in matched_sessions[:3]:
                    lines.append(f"- Focus in **{s.get('app_class')}**: {s.get('title') or 'session'} ({fmt_secs(s.get('seconds', 0))})")
            else:
                lines.append(f"- Summary for {sec_title} during tracked focus period.")

    # Questions for tomorrow
    if questions_for_tomorrow:
        lines += ["", "## Questions for Tomorrow", ""]
        if top_apps:
            lines.append(f"- What is the primary next step to continue progress in **{top_apps[0]['app']}**?")
        else:
            lines.append("- What is the single highest-priority objective for tomorrow?")
        if notes:
            lines.append("- Which captured items from today should be turned into immediate action items?")
        else:
            lines.append("- Are all open tasks and pull requests ready for review?")

    return "\n".join(lines)


def effective_body(row: dict | None) -> str:
    """Return the human-edited report body if present, else AI summary_md."""
    if not row:
        return ""
    edited = row.get("edited_body")
    if edited and edited.strip():
        return edited
    return row.get("summary_md") or ""


def mirror_to_vault(cfg: Config, day: str, md: str) -> None:
    """Optional vault copy — off by default; the report lives inside the app."""
    if not (cfg.activity.mirror_daily_log or cfg.paths.vault_sync):
        return
    try:
        vault = expand_path(cfg.paths.vault_dir)
        d = vault / "Daily"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{day}.md").write_text(md + "\n", encoding="utf-8")
    except OSError:
        log.exception("failed to mirror daily log for %s", day)


def build_evidence(
    md: str,
    sessions: list[dict],
    notes: list[dict] | None = None,
    git: list[dict] | None = None,
) -> list[dict]:
    """Link digest sections and sentences/bullets to underlying sessions, notes and commits (#73, #350)."""
    notes = notes or []
    git = git or []
    evidence: list[dict] = []

    def session_matches(text: str, s: dict) -> bool:
        low = text.lower()
        app = (s.get("app_class") or "").lower()
        if app and app in low:
            return True
        title = (s.get("title") or "").lower()
        words = [w for w in re.findall(r"[a-zA-Z0-9_.-]{4,}", title) if w not in {"https", "http", "www", "com", "org", "page", "window"}]
        for w in words:
            if w in low:
                return True
        proj = (s.get("project") or "").lower()
        if proj and proj in low:
            return True
        return False

    def note_matches(text: str, n: dict) -> bool:
        low = text.lower()
        title = (n.get("title") or "").lower()
        if not title:
            return False
        if title in low:
            return True
        words = [w for w in re.findall(r"[a-zA-Z0-9_.-]{4,}", title) if w not in {"note", "todo", "task"}]
        for w in words:
            if w in low:
                return True
        return False

    def commit_matches(text: str, c: dict) -> bool:
        low = text.lower()
        repo = (c.get("repo") or "").lower()
        if repo and repo in low:
            return True
        subj = (c.get("subject") or "").lower()
        words = [w for w in re.findall(r"[a-zA-Z0-9_.-]{4,}", subj) if w not in {"feat", "fix", "docs", "chore", "test"}]
        for w in words:
            if w in low:
                return True
        return False

    def format_session(s: dict) -> dict:
        return {
            "id": s.get("id"),
            "app": s.get("app_class", ""),
            "title": s.get("title", ""),
            "seconds": s.get("seconds", 0),
            "start": (s.get("first_seen") or "")[11:16],
            "end": (s.get("last_seen") or "")[11:16],
        }

    def format_note(n: dict) -> dict:
        return {
            "id": n.get("id", ""),
            "title": n.get("title", ""),
        }

    def format_commit(c: dict) -> dict:
        return {
            "repo": c.get("repo", ""),
            "subject": c.get("subject", ""),
        }

    section_chunks = re.split(r"(?m)^##\s+", md)
    for chunk in section_chunks[1:]:
        lines = chunk.strip().splitlines()
        if not lines:
            continue
        sec_title = lines[0].strip()

        sec_sessions = [format_session(s) for s in sessions if session_matches(chunk, s)]
        sec_notes = [format_note(n) for n in notes if note_matches(chunk, n)]
        sec_commits = [format_commit(c) for c in git if commit_matches(chunk, c)]

        if "captured notes" in sec_title.lower() and not sec_notes and notes:
            sec_notes = [format_note(n) for n in notes[:5]]

        evidence.append({
            "section": sec_title,
            "text": sec_title,
            "sessions": sec_sessions,
            "notes": sec_notes,
            "commits": sec_commits,
        })

        for line in lines[1:]:
            line_str = line.strip()
            if not line_str:
                continue
            is_bullet = line_str.startswith(("-", "*")) or bool(re.match(r"^\d+\.", line_str))
            clean_line = re.sub(r"^[-*]\s+|\d+\.\s+", "", line_str).strip()

            sentences = [clean_line] if is_bullet else [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_line) if s.strip()]

            for sent in sentences:
                if len(sent) < 8:
                    continue
                item_sessions = [format_session(s) for s in sessions if session_matches(sent, s)]
                item_notes = [format_note(n) for n in notes if note_matches(sent, n)]
                item_commits = [format_commit(c) for c in git if commit_matches(sent, c)]

                if "captured notes" in sec_title.lower() and not item_notes and notes:
                    for n in notes:
                        if note_matches(sent, n):
                            item_notes.append(format_note(n))

                if item_sessions or item_notes or item_commits:
                    evidence.append({
                        "section": sec_title,
                        "text": sent,
                        "sessions": item_sessions,
                        "notes": item_notes,
                        "commits": item_commits,
                    })

    return evidence


async def generate_daily_log(
    db: Database,
    cfg: Config,
    day: str,
    *,
    rolling: bool = False,
    tone: str = "balanced",
    length: str = "medium",
    start_time: str | None = None,
    end_time: str | None = None,
    highlights_only: bool = False,
    questions_for_tomorrow: bool = False,
    custom_sections: list[dict] | None = None,
    prompt_override: str | None = None,
) -> dict:
    """Generate (or regenerate) the daily log. Returns the row.

    rolling=True covers the past 24 hours ending now (the 12:00 AM report);
    default mode covers the calendar day (browsing past days).
    """
    from ..activity import app_blocked
    from ..services.files_activity import (
        collect_git_subjects,
        render_files_activity,
        scan_recent_files,
    )

    now = datetime.now().astimezone()
    if rolling:
        cutoff = now - timedelta(hours=24)
        sessions = [
            s for s in db.activity_since(cutoff.isoformat(timespec="seconds"))
            if not app_blocked(cfg.activity, db, s["app_class"])
        ]
        since, until = cutoff, now
    else:
        sessions = [
            s for s in db.activity_sessions(day)
            if not app_blocked(cfg.activity, db, s["app_class"])
        ]
        since = datetime.fromisoformat(f"{day}T00:00:00").astimezone()
        until = since + timedelta(days=1)

    if start_time:
        try:
            st_parts = [int(p) for p in start_time.split(":")]
            st_dt = since.replace(hour=st_parts[0], minute=st_parts[1], second=0)
            since = max(since, st_dt)
            sessions = [
                s for s in sessions
                if (s.get("last_seen") or s.get("first_seen", ""))[11:16] >= start_time
            ]
        except Exception:
            pass

    if end_time:
        try:
            et_parts = [int(p) for p in end_time.split(":")]
            et_dt = since.replace(hour=et_parts[0], minute=et_parts[1], second=0)
            until = min(until, et_dt)
            sessions = [
                s for s in sessions
                if (s.get("first_seen") or s.get("last_seen", ""))[11:16] <= end_time
            ]
        except Exception:
            pass

    watch_dirs = [expand_path(p.strip()) for p in cfg.activity.watch_dirs.split(",") if p.strip()]
    scan = scan_recent_files(watch_dirs, since=since, until=until)
    git = collect_git_subjects(watch_dirs, since=since, until=until)
    notes = collect_notes_context(db, since, until)

    if not sessions and not scan["total"] and not notes:
        raise ValueError("no tracked activity in this window")

    # Persist commit subjects so they become searchable; the collection pass
    # already ran for the report, so this costs nothing extra.
    try:
        from .search import persist_commits

        persist_commits(db, git, until=until)
    except Exception:
        log.warning("daily log: could not persist commits for search", exc_info=True)

    files_block = render_files_activity(scan, git)
    notes_block = render_notes_context(notes)

    transcript = build_transcript(sessions) if sessions else "No window sessions recorded."
    transcript = (
        f"Window: {since.strftime('%Y-%m-%d %H:%M')} → {until.strftime('%Y-%m-%d %H:%M')} "
        "(local time)\n\n"
        + transcript
        + "\n\n"
        + files_block
        + "\n\n"
        + notes_block
    )

    try:
        md, model = await generate_with_llm(
            transcript,
            day,
            cfg,
            tone=tone,
            length=length,
            highlights_only=highlights_only,
            questions_for_tomorrow=questions_for_tomorrow,
            custom_sections=custom_sections,
            prompt_override=prompt_override,
        )
    except Exception as exc:  # LLMUnavailable or any model failure
        log.info("daily log via LLM unavailable (%s) — using fallback digest", exc)
        md, model = (
            fallback_digest(
                sessions,
                day,
                scan=scan,
                git=git,
                notes=notes,
                tone=tone,
                length=length,
                highlights_only=highlights_only,
                questions_for_tomorrow=questions_for_tomorrow,
                custom_sections=custom_sections,
            ),
            "fallback",
        )

    if rolling and "past 24 hours" not in md.lower() and "24 hours" not in md.lower():
        md = re.sub(
            r"^#\s+Daily (?:Digest|log)\s+—\s+" + re.escape(day),
            f"# Daily Digest — {day} (past 24 hours)",
            md,
            count=1,
        )

    evidence_list = build_evidence(md, sessions, notes=notes, git=git)
    evidence_json = json.dumps(evidence_list) if evidence_list else None

    db.upsert_daily_log(
        day, md, model, evidence=evidence_json, prompt_override=prompt_override
    )
    row = db.get_daily_log(day)
    mirror_to_vault(cfg, day, effective_body(row))
    from ..notify import send

    send("Fleeting", f"Your daily digest for {day} is ready — open the app to read it.")
    return row  # type: ignore[return-value]


REFLECTION_PROMPTS = [
    "What gave you momentum today, and what drained your focus?",
    "What was the most rewarding problem you solved or progressed on?",
    "Where did unexpected friction pull you off track, and how would you avoid it next time?",
    "What is one key insight or learning from today worth carrying into tomorrow?",
    "If you could redo one hour of today's work, what would you spend it on?",
]


def get_reflection_prompts(day: str, report_md: str = "") -> list[str]:
    """Return tailored reflection journaling prompts for the day's digest (#347)."""
    prompts = list(REFLECTION_PROMPTS)
    if report_md:
        low = report_md.lower()
        if "git" in low or "commit" in low:
            prompts.insert(0, "What was the most significant code change or architectural decision you made today?")
        if "research" in low or "firefox" in low or "chrome" in low:
            prompts.insert(0, "What was the most surprising takeaway from your reading and research today?")
    return prompts


async def preview_daily_log_playground(
    db: Database,
    cfg: Config,
    day: str,
    *,
    tone: str = "balanced",
    length: str = "medium",
    highlights_only: bool = False,
    questions_for_tomorrow: bool = False,
    custom_sections: list[dict] | None = None,
    prompt_override: str | None = None,
) -> dict:
    """#349 Report playground: test prompt changes against telemetry without persisting."""
    from ..activity import app_blocked
    from ..services.files_activity import (
        collect_git_subjects,
        render_files_activity,
        scan_recent_files,
    )

    since = datetime.fromisoformat(f"{day}T00:00:00").astimezone()
    until = since + timedelta(days=1)
    sessions = [
        s for s in db.activity_sessions(day)
        if not app_blocked(cfg.activity, db, s["app_class"])
    ]
    watch_dirs = [expand_path(p.strip()) for p in cfg.activity.watch_dirs.split(",") if p.strip()]
    scan = scan_recent_files(watch_dirs, since=since, until=until)
    git = collect_git_subjects(watch_dirs, since=since, until=until)
    notes = collect_notes_context(db, since, until)

    files_block = render_files_activity(scan, git)
    notes_block = render_notes_context(notes)
    transcript = build_transcript(sessions) if sessions else "No window sessions recorded."
    full_transcript = (
        f"Window: {since.strftime('%Y-%m-%d %H:%M')} → {until.strftime('%Y-%m-%d %H:%M')} "
        "(local time)\n\n"
        + transcript
        + "\n\n"
        + files_block
        + "\n\n"
        + notes_block
    )

    system_prompt = build_effective_prompt(
        day,
        tone=tone,
        highlights_only=highlights_only,
        questions_for_tomorrow=questions_for_tomorrow,
        custom_sections=custom_sections,
        prompt_override=prompt_override,
        db=db,  # #93: the user's edited template, when they have one
    )

    try:
        md, model = await generate_with_llm(
            full_transcript,
            day,
            cfg,
            tone=tone,
            length=length,
            highlights_only=highlights_only,
            questions_for_tomorrow=questions_for_tomorrow,
            custom_sections=custom_sections,
            prompt_override=prompt_override,
        )
    except Exception as exc:
        log.info("playground via LLM unavailable (%s) — using fallback digest", exc)
        md = fallback_digest(
            sessions,
            day,
            scan=scan,
            git=git,
            notes=notes,
            tone=tone,
            length=length,
            highlights_only=highlights_only,
            questions_for_tomorrow=questions_for_tomorrow,
            custom_sections=custom_sections,
        )
        model = "fallback"

    return {
        "day": day,
        "system_prompt": system_prompt,
        "transcript": full_transcript,
        "preview_md": md,
        "model": model,
    }


