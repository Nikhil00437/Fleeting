"""Computer activity collector (Hyprland).

Polls the active window and cursor position every `poll_secs`, merging
consecutive samples into compact per-window sessions with accumulated active
seconds. Idle detection: when the cursor hasn't moved for `idle_after_min`
minutes the session stops accruing time (keyboard-only AFK is the accepted
trade-off; cursor+window-change is the normal signal).

Everything is stored locally in SQLite. Pause anytime from the UI
(kv flag), and exclude apps by class substring in settings.

Design note: the state machine (`poll_once`) is separate from the probes so
tests can drive it with synthetic windows without Hyprland.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from .config import ActivityConfig
from .services.projects import detect_project

log = logging.getLogger("fleeting.activity")

TITLE_MAX = 120

# #66 redaction. Emails go unconditionally — a window title is the single
# most common place a stray address ends up (mail, forms, logins) — and any
# configured token matches as a plain substring, case-insensitively. Applied
# at write time: a redacted title that only disappeared on read would still
# be sitting in the DB, which is the whole point of the rule.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
REDACTED = "\u00abredacted\u00bb"


def idle_minutes_for(db, cfg: ActivityConfig, app_class: str) -> int:
    """#340 the idle threshold that applies to one app right now."""
    return int(db.app_idle_rules().get(app_class, cfg.idle_after_min))


def resolve_app_class(db, app_class: str) -> str:
    """#64: follow rename/merge aliases to the canonical class.

    A cycle (a→b, b→a) is possible in a hand-edited table, so the walk is
    bounded by the number of aliases rather than trusting the data.
    """
    aliases = db.app_aliases()
    seen = {app_class}
    current = app_class
    while current in aliases:
        nxt = aliases[current]
        if nxt in seen:
            log.warning("app alias cycle at %r; keeping %r", current, app_class)
            break
        seen.add(nxt)
        current = nxt
    return current


def set_app_alias(db, from_class: str, to_class: str) -> None:
    """Rename `from_class` to `to_class`, folding its history in.

    Rewriting the rows is the point of a merge: leaving yesterday's
    `firefox-esr` untouched would split the day in two, which is the exact
    mess the rename exists to clean up. The activity FTS trigger keeps the
    search index in step with the UPDATE.
    """
    from_class, to_class = from_class.strip(), to_class.strip()
    if not from_class or not to_class:
        raise ValueError("both app classes are required")
    if from_class == to_class:
        raise ValueError("source and target are the same")
    db.execute(
        "INSERT INTO app_aliases (from_class, to_class, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(from_class) DO UPDATE SET to_class=excluded.to_class,"
        " updated_at=excluded.updated_at",
        (from_class, to_class, _local_iso(_local_now())),
    )
    db.execute("UPDATE activity SET app_class = ? WHERE app_class = ?", (to_class, from_class))
    db.commit()


def delete_app_alias(db, from_class: str) -> bool:
    cur = db.execute("DELETE FROM app_aliases WHERE from_class = ?", (from_class,))
    db.commit()
    return cur.rowcount > 0


def git_context(cwd: str | os.PathLike[str]) -> tuple[str, str] | None:
    """#336 (repo dir name, branch) for a working directory, or None.

    Reads `.git/HEAD` directly rather than shelling out to git: this runs once
    per session, but a subprocess per window switch is a needless tax, and the
    answer is a two-line file read.
    """
    path = Path(os.fsdecode(cwd)) if not isinstance(cwd, str) else Path(cwd)
    for parent in (path, *path.parents):
        head = parent / ".git" / "HEAD"
        try:
            content = head.read_text().strip()
        except OSError:
            continue
        if content.startswith("ref: refs/heads/"):
            return parent.name, content[len("ref: refs/heads/"):]
        return parent.name, content[:7]  # detached HEAD
    return None


def redact_title(title: str, patterns: list[str] | None = None) -> str:
    """Scrub a window title.

    A configured pattern takes the whole whitespace-delimited token with it,
    not just the literal: people configure `ghp_` meaning "any GitHub token",
    and leaving `«redacted»TOTALLYSECRET` behind would defeat the point.
    """
    out = _EMAIL_RE.sub(REDACTED, title or "")
    for pat in patterns or []:
        pat = pat.strip()
        if not pat:
            continue
        out = re.sub(rf"\S*{re.escape(pat)}\S*", REDACTED, out, flags=re.IGNORECASE)
    return out


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _local_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def probe_hyprland() -> tuple[dict | None, tuple[int, int] | None]:
    """Default probe: (active window {class,title,workspace} | None, cursor | None)."""
    win = None
    cursor = None
    try:
        out = subprocess.run(
            ["hyprctl", "-j", "activewindow"], capture_output=True, timeout=5
        ).stdout.decode(errors="replace")
        data = json.loads(out)
        if isinstance(data, dict) and data.get("class"):
            win = {
                "class": str(data["class"]),
                "title": str(data.get("title") or "")[:TITLE_MAX],
                "pid": data.get("pid"),
            }
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    # #338 the workspace is a property of the window, not the session, and it
    # costs one more hyprcall; a failure here must not cost the window itself.
    if win is not None:
        try:
            ws = json.loads(
                subprocess.run(
                    ["hyprctl", "-j", "activeworkspace"], capture_output=True, timeout=5
                ).stdout.decode(errors="replace")
            )
            if isinstance(ws, dict) and ws.get("id") is not None:
                win["workspace"] = str(ws["id"])
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
    try:
        out = subprocess.run(["hyprctl", "cursorpos"], capture_output=True, timeout=5).stdout.decode()
        x, y = out.split(",")
        cursor = (int(x.strip()), int(y.strip()))
    except (subprocess.SubprocessError, ValueError, OSError):
        pass
    return win, cursor


def app_blocked(cfg: ActivityConfig, db, app_class: str) -> bool:
    """Effective tracking decision for an app.

    Per-app rules (settings toggles) win; otherwise the config blocklist
    (excluded_apps, e.g. the zen browser) decides; unknown apps are tracked.
    """
    rules = db.app_rules()
    if app_class in rules:
        return not rules[app_class]
    blocklist = [e.strip().lower() for e in cfg.excluded_apps.split(",") if e.strip()]
    low = app_class.lower()
    return any(e in low for e in blocklist)


class ActivityCollector:
    def __init__(
        self,
        db,
        cfg: ActivityConfig,
        probe: Callable[[], tuple[dict | None, tuple[int, int] | None]] = probe_hyprland,
        on_day_rollover: Callable[[str], Awaitable[None]] | None = None,
        on_screentime_milestone: Callable[[str, int], Awaitable[None]] | None = None,
        on_tick: Callable[[dict | None], None] | None = None,
    ):
        self.db = db
        self.cfg = cfg
        self.probe = probe
        self.on_day_rollover = on_day_rollover
        self.on_screentime_milestone = on_screentime_milestone
        self.on_tick = on_tick
        self.running = False
        self.last_error: str | None = None

        # state machine
        self.current: dict | None = None      # open session being accumulated
        self._last_cursor: tuple[int, int] | None = None
        self._idle_streak_secs = 0
        self._today: str = _local_now().strftime("%Y-%m-%d")
        # #335 the tail of the current block: {end, project, id}. A session
        # continues it when it starts soon after and on the same project.
        self._last_block: dict | None = None
        self._block_seq = 0
        self._redact: list[str] = [p.strip() for p in cfg.redact_patterns.split(",") if p.strip()]
        self._watch_dirs: list[str] = [w.strip() for w in cfg.watch_dirs.split(",") if w.strip()]

    # ---- public ----------------------------------------------------------

    def is_paused(self) -> bool:
        return self.db.kv_get("activity_paused", "0") == "1"

    def set_paused(self, paused: bool) -> None:
        self.db.kv_set("activity_paused", "1" if paused else "0")
        if paused:
            self._close_current()

    def current_session(self) -> dict | None:
        if self.is_paused():
            return None
        return dict(self.current) if self.current else None

    def today_screentime_seconds(self) -> int:
        today = _local_now().strftime("%Y-%m-%d")
        sessions = [
            s for s in self.db.activity_sessions(today)
            if not app_blocked(self.cfg, self.db, s["app_class"])
        ]
        total = sum(int(s.get("seconds", 0)) for s in sessions)
        if self.current and not app_blocked(self.cfg, self.db, self.current["app_class"]):
            current_day = self.current.get("day") or (self.current["first_seen"][:10] if "first_seen" in self.current else today)
            if current_day == today:
                persisted_ids = {s.get("id"): int(s.get("seconds", 0)) for s in sessions if s.get("id") is not None}
                row_id = self.current.get("row_id")
                curr_secs = int(self.current.get("seconds", 0))
                if row_id is None or row_id not in persisted_ids:
                    total += curr_secs
                elif curr_secs > persisted_ids[row_id]:
                    total += (curr_secs - persisted_ids[row_id])
        return total

    def check_screentime_milestones(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        if not self.on_screentime_milestone or not self.cfg.auto_daily_log:
            return
        total = self.today_screentime_seconds()
        hours = total // 3600
        if hours < 1:
            return
        today = _local_now().strftime("%Y-%m-%d")
        try:
            last = int(self.db.kv_get(f"digest_screentime_hours_{today}", "0") or "0")
        except (ValueError, TypeError):
            last = 0
        if hours > last:
            self.db.kv_set(f"digest_screentime_hours_{today}", str(hours))
            if loop is not None:
                asyncio.run_coroutine_threadsafe(self._safe_milestone(today, hours), loop)
            else:
                try:
                    cur_loop = asyncio.get_running_loop()
                except RuntimeError:
                    cur_loop = None

                if cur_loop is not None and cur_loop.is_running():
                    cur_loop.create_task(self._safe_milestone(self._today, hours))
                else:
                    try:
                        asyncio.run(self._safe_milestone(self._today, hours))
                    except RuntimeError:
                        pass

    async def run(self) -> None:
        import shutil

        if not shutil.which("hyprctl"):
            log.warning("hyprctl not found — activity tracking disabled (Hyprland only for now)")
            return
        self.running = True
        loop = asyncio.get_running_loop()
        log.info(
            "activity collector started (poll=%ss, idle>%smin, excluded=%r)",
            self.cfg.poll_secs, self.cfg.idle_after_min, self.cfg.excluded_apps,
        )
        try:
            while True:
                try:
                    await asyncio.to_thread(self.step, loop)
                    self.last_error = None
                except Exception as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    log.warning("activity poll failed: %s", self.last_error)
                if self.on_tick:
                    try:
                        self.on_tick(self.current_session())
                    except Exception:
                        log.exception("activity tick callback failed")
                await asyncio.sleep(max(5, self.cfg.poll_secs))
        finally:
            self.running = False

    def step(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """One probe + state transition. Also detects day rollover."""
        if _local_now().strftime("%Y-%m-%d") != self._today:
            finished_day = self._today
            self._close_current()
            self._today = _local_now().strftime("%Y-%m-%d")
            if self.on_day_rollover and self.cfg.auto_daily_log:
                if loop is not None:
                    asyncio.run_coroutine_threadsafe(self._safe_rollover(finished_day), loop)
                # else: tests drive rollover explicitly

        if self.is_paused():
            return

        win, cursor = self.probe()
        now = _local_now()
        self.poll_once(win, cursor, now)
        self.check_screentime_milestones(loop)

    async def _safe_rollover(self, day: str) -> None:
        try:
            if self.on_day_rollover:
                await self.on_day_rollover(day)
        except Exception:
            log.exception("daily log generation for %s failed", day)

    async def _safe_milestone(self, day: str, hours: int) -> None:
        try:
            if self.on_screentime_milestone:
                res = self.on_screentime_milestone(day, hours)
                if inspect.isawaitable(res):
                    await res
        except Exception:
            log.exception("screentime milestone callback failed for %s (%d hrs)", day, hours)

    # ---- state machine ----------------------------------------------------

    def poll_once(self, win: dict | None, cursor: tuple[int, int] | None, now: datetime) -> None:
        if win is not None:
            # #64 the app is renamed once, here, so the session key and every
            # stored row agree on which app this was.
            app_class = resolve_app_class(self.db, win["class"])
            if self._excluded(app_class):
                win = None

        moved = cursor is not None and cursor != self._last_cursor
        if cursor is not None:
            self._idle_streak_secs = 0 if moved else self._idle_streak_secs + self.cfg.poll_secs
        self._last_cursor = cursor
        idle = self._idle_streak_secs >= (
            idle_minutes_for(self.db, self.cfg, app_class) * 60 if win else 0
        )

        if win is None:
            self._close_current()
            return

        # #66: redact before anything reaches the session dict or the DB, so
        # the raw title is never persisted and never sits in memory longer.
        title = redact_title(win.get("title") or "", self._redact)[:TITLE_MAX]
        workspace = win.get("workspace")

        # accrue real elapsed time, clamped so suspend/resume or hiccups
        # don't credit one poll with hours
        max_step = self.cfg.poll_secs * 2
        key = (app_class, title)
        if self.current and (self.current["app_class"], self.current["title"]) == key:
            elapsed = (now - datetime.fromisoformat(self.current["last_seen"])).total_seconds()
            self.current["last_seen"] = _local_iso(now)
            step = int(min(max(elapsed, 0), max_step))
            if idle:
                # The AFK stretch still belongs to this session — it is just not
                # work, so it is stored apart (#340).
                self.current["idle_secs"] = self.current.get("idle_secs", 0) + step
            else:
                self.current["seconds"] += step
            self.current["row_id"] = self.db.upsert_activity(self._row(self.current))
        else:
            self._close_current()
            ctx = git_context(cwd) if (cwd := self._cwd_of(win.get("pid"))) else None
            # #53 detected once, at session open: a later title change must not
            # retroactively relabel the time already spent.
            project = detect_project(
                title, repo=ctx[0] if ctx else None, roots=self._watch_dirs
            )
            block_id = self._block_for(now, project)
            self.current = {
                "app_class": app_class,
                "title": title,
                "workspace": workspace,
                "repo": ctx[0] if ctx else None,
                "branch": ctx[1] if ctx else None,
                "project": project,
                "block_id": block_id,
                "first_seen": _local_iso(now),
                "last_seen": _local_iso(now),
                "seconds": 0,
                "idle_secs": 0,
                "row_id": None,
            }
            self.current["row_id"] = self.db.upsert_activity(self._row(self.current))

    def _block_for(self, now: datetime, project: str | None) -> str:
        """#335: the block this session belongs to, extending the current one
        when it starts soon after it and stays on the same project."""
        day = now.strftime("%Y-%m-%d")
        tail = self._last_block
        if tail and tail["project"] == project:
            gap = (now - datetime.fromisoformat(tail["end"])).total_seconds()
            if 0 <= gap <= self.cfg.block_gap_min * 60:
                return str(tail["id"])
        self._block_seq += 1
        return f"{day}-{self._block_seq}"

    def _cwd_of(self, pid: object) -> str | None:
        """#336: the working directory behind a window, via /proc."""
        if not isinstance(pid, int) or pid <= 0:
            return None
        try:
            return os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            return None

    def _excluded(self, app_class: str) -> bool:
        return app_blocked(self.cfg, self.db, app_class)

    def _row(self, session: dict) -> dict:
        return {
            "id": session.get("row_id"),
            "app_class": session["app_class"],
            "title": session["title"],
            "first_seen": session["first_seen"],
            "last_seen": session["last_seen"],
            "seconds": session["seconds"],
            "day": session["first_seen"][:10],
            # #338 pinned at session start: a workspace switch mid-session is
            # history that already happened on the old workspace.
            "idle_secs": session.get("idle_secs", 0),
            "workspace": (str(session["workspace"]) if session.get("workspace") is not None else None),
            "repo": session.get("repo"),
            "branch": session.get("branch"),
            "project": session.get("project"),
            # #335 set when the session opened; a poll must never reassign it.
            "block_id": session.get("block_id"),
        }

    def _close_current(self) -> None:
        if self.current:
            self._last_block = {
                "end": self.current["last_seen"],
                "project": self.current.get("project"),
                "id": self.current.get("block_id"),
            }
        self.current = None


def group_blocks(sessions: list[dict]) -> list[dict]:
    """#335 view model: the work blocks of a day, in order.

    Rows written before this feature carry no block_id; consecutive ones fall
    back to a single block per session rather than being dropped.
    """
    blocks: dict[str, dict] = {}
    for s in sessions:
        key = s.get("block_id") or f"row-{s.get('id')}"
        block = blocks.setdefault(
            key,
            {
                "id": key,
                "start": s["first_seen"],
                "end": s["last_seen"],
                "seconds": 0,
                "project": s.get("project"),
                "apps": [],
            },
        )
        block["seconds"] += int(s.get("seconds") or 0)
        block["end"] = max(block["end"], s["last_seen"])
        if s["app_class"] not in block["apps"]:
            block["apps"].append(s["app_class"])
        if block["project"] is None:
            block["project"] = s.get("project")
    return sorted(blocks.values(), key=lambda b: b["start"])


def aggregate_day(sessions: list[dict]) -> dict:
    """Compact view model for one day: totals per app + chronological sessions."""
    apps: dict[str, dict] = {}
    for s in sessions:
        app = apps.setdefault(s["app_class"], {"app": s["app_class"], "seconds": 0, "titles": {}})
        app["seconds"] += s["seconds"]
        title = s["title"] or "(no title)"
        app["titles"][title] = app["titles"].get(title, 0) + s["seconds"]
    for app in apps.values():
        app["titles"] = [
            {"title": t, "seconds": secs}
            for t, secs in sorted(app["titles"].items(), key=lambda kv: -kv[1])
        ][:10]
    apps_list = sorted(apps.values(), key=lambda a: -a["seconds"])
    ordered = sorted(sessions, key=lambda s: s["first_seen"])
    return {
        "total_seconds": sum(a["seconds"] for a in apps_list),
        "apps": apps_list,
        "sessions": ordered,
        "blocks": group_blocks(ordered),
    }
