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
import subprocess
from datetime import datetime
from typing import Awaitable, Callable

from .config import ActivityConfig

log = logging.getLogger("fleeting.activity")

TITLE_MAX = 120


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _local_iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def probe_hyprland() -> tuple[dict | None, tuple[int, int] | None]:
    """Default probe: (active window {class,title} | None, cursor (x,y) | None)."""
    win = None
    cursor = None
    try:
        out = subprocess.run(
            ["hyprctl", "-j", "activewindow"], capture_output=True, timeout=5
        ).stdout.decode(errors="replace")
        data = json.loads(out)
        if isinstance(data, dict) and data.get("class"):
            win = {"class": str(data["class"]), "title": str(data.get("title") or "")[:TITLE_MAX]}
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
        sessions = [
            s for s in self.db.activity_sessions(self._today)
            if not app_blocked(self.cfg, self.db, s["app_class"])
        ]
        total = sum(int(s.get("seconds", 0)) for s in sessions)
        if self.current and not app_blocked(self.cfg, self.db, self.current["app_class"]):
            current_day = self.current.get("day") or (self.current["first_seen"][:10] if "first_seen" in self.current else self._today)
            if current_day == self._today:
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
        try:
            last = int(self.db.kv_get(f"digest_screentime_hours_{self._today}", "0") or "0")
        except (ValueError, TypeError):
            last = 0
        if hours > last:
            self.db.kv_set(f"digest_screentime_hours_{self._today}", str(hours))
            if loop is not None:
                asyncio.run_coroutine_threadsafe(self._safe_milestone(self._today, hours), loop)
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
        moved = cursor is not None and cursor != self._last_cursor
        if cursor is not None:
            self._idle_streak_secs = 0 if moved else self._idle_streak_secs + self.cfg.poll_secs
        self._last_cursor = cursor
        idle = self._idle_streak_secs >= self.cfg.idle_after_min * 60

        if win is None or self._excluded(win["class"]):
            self._close_current()
            return

        # accrue real elapsed time, clamped so suspend/resume or hiccups
        # don't credit one poll with hours
        max_step = self.cfg.poll_secs * 2
        key = (win["class"], win["title"])
        if self.current and (self.current["app_class"], self.current["title"]) == key:
            elapsed = (now - datetime.fromisoformat(self.current["last_seen"])).total_seconds()
            self.current["last_seen"] = _local_iso(now)
            if not idle:
                self.current["seconds"] += int(min(max(elapsed, 0), max_step))
            self.current["row_id"] = self.db.upsert_activity(self._row(self.current))
        else:
            self._close_current()
            self.current = {
                "app_class": win["class"],
                "title": win["title"],
                "first_seen": _local_iso(now),
                "last_seen": _local_iso(now),
                "seconds": 0,
                "row_id": None,
            }
            self.current["row_id"] = self.db.upsert_activity(self._row(self.current))

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
        }

    def _close_current(self) -> None:
        self.current = None


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
    return {
        "total_seconds": sum(a["seconds"] for a in apps_list),
        "apps": apps_list,
        "sessions": sorted(
            sessions,
            key=lambda s: s["first_seen"],
        ),
    }
