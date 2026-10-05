"""Daily log generation: synthesize raw window sessions, project files, git commits,
and captured notes into an actionable, high-signal daily work & memory digest.

The local LLM (Ollama / LM Studio) writes the digest; if it's unavailable a
smart deterministic synthesis is produced instead (merging focus blocks,
extracting window topics, and summarizing project files/commits/tasks without
noisy 0-minute switches or redundant app tables).
"""

from __future__ import annotations

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


async def generate_with_llm(transcript: str, day: str, cfg) -> tuple[str, str]:
    """Returns (markdown, model_used). Raises LLMUnavailable."""
    from ..services import llm as llm_svc

    if cfg.llm.provider == "none":
        raise llm_svc.LLMUnavailable("llm disabled")
    base = cfg.llm.base_url.rstrip("/")
    if cfg.llm.provider == "lmstudio":
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": DAILY_LOG_SYSTEM.replace("{date}", day)},
                {"role": "user", "content": transcript},
            ],
            "temperature": 0.35,
            "max_tokens": 1400,
        }
        url = f"{base}/v1/chat/completions"
    else:
        payload = {
            "model": cfg.llm.model,
            "messages": [
                {"role": "system", "content": DAILY_LOG_SYSTEM.replace("{date}", day)},
                {"role": "user", "content": transcript},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.35, "num_predict": 1400},
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
    return md, cfg.llm.model or "local"


def fallback_digest(
    sessions: list[dict],
    day: str,
    *,
    scan: dict | None = None,
    git: list[dict] | None = None,
    notes: list[dict] | None = None,
) -> str:
    """Smart deterministic synthesis when no LLM is available (no raw 0m spam or redundant tables)."""
    agg = aggregate_day(sessions)
    total = agg["total_seconds"]
    lines = [f"# Daily Digest — {day}", "", "## Executive Summary", ""]
    if total == 0 and not (scan and scan.get("total")):
        lines.append("No tracked activity recorded in this window.")
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

    return "\n".join(lines)


def mirror_to_vault(cfg: Config, day: str, md: str) -> None:
    """Optional vault copy — off by default; the report lives inside the app."""
    if not cfg.activity.mirror_daily_log:
        return
    try:
        vault = expand_path(cfg.paths.vault_dir)
        d = vault / "Daily"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{day}.md").write_text(md + "\n", encoding="utf-8")
    except OSError:
        log.exception("failed to mirror daily log for %s", day)


async def generate_daily_log(db: Database, cfg: Config, day: str, *, rolling: bool = False) -> dict:
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
        md, model = await generate_with_llm(transcript, day, cfg)
    except Exception as exc:  # LLMUnavailable or any model failure
        log.info("daily log via LLM unavailable (%s) — using fallback digest", exc)
        md, model = (
            fallback_digest(sessions, day, scan=scan, git=git, notes=notes),
            "fallback",
        )

    if rolling and "past 24 hours" not in md.lower() and "24 hours" not in md.lower():
        md = re.sub(
            r"^#\s+Daily (?:Digest|log)\s+—\s+" + re.escape(day),
            f"# Daily Digest — {day} (past 24 hours)",
            md,
            count=1,
        )

    db.upsert_daily_log(day, md, model)
    mirror_to_vault(cfg, day, md)
    from ..notify import send

    send("Fleeting", f"Your daily digest for {day} is ready — open the app to read it.")
    return db.get_daily_log(day)  # type: ignore[return-value]
