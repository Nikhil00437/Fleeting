"""Activity collector state machine + daily log generation tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from fleeting.activity import ActivityCollector, aggregate_day
from fleeting.config import ActivityConfig
from fleeting.services.dailylog import build_transcript, fallback_digest


class FakeDB:
    """Minimal in-memory stand-in for Database (upsert/kv only)."""

    def __init__(self):
        self.rows: list[dict] = []
        self.store: dict[str, str] = {}

    def upsert_activity(self, row):
        if row.get("id") is not None:
            self.rows[row["id"]] = dict(row)
            return row["id"]
        r = dict(row)
        r["id"] = len(self.rows)
        self.rows.append(r)
        return r["id"]

    def activity_sessions(self, day: str) -> list[dict]:
        return [dict(r) for r in self.rows if r.get("day") == day and r.get("seconds", 0) >= 1]

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value

    def app_rules(self):
        return getattr(self, "rules", {})

    def app_aliases(self):
        return getattr(self, "aliases", {})


def make_collector(poll=20, idle_min=3, on_screentime_milestone=None, auto_daily_log=True):
    cfg = ActivityConfig(poll_secs=poll, idle_after_min=idle_min, auto_daily_log=auto_daily_log)
    return ActivityCollector(
        FakeDB(),
        cfg,
        probe=lambda: (None, None),
        on_screentime_milestone=on_screentime_milestone,
    )


_BASE = datetime(2026, 9, 30, 10, 0, 0)


def t(seconds: int) -> datetime:
    """Time `seconds` after the 10:00:00 base."""
    return _BASE + timedelta(seconds=seconds)


def test_poll_creates_and_extends_session():
    c = make_collector()
    win = {"class": "code", "title": "fleeting — process.py"}
    c.poll_once(win, (5, 5), t(0))
    c.poll_once(win, (9, 5), t(20))
    assert c.current["seconds"] == 20
    assert len(c.db.rows) == 1
    assert c.db.rows[0]["seconds"] == 20


def test_window_switch_closes_session():
    c = make_collector()
    c.poll_once({"class": "code", "title": "a"}, (5, 5), t(0))
    c.poll_once({"class": "code", "title": "b"}, (5, 5), t(20))
    c.poll_once({"class": "zen", "title": "docs"}, (5, 5), t(40))
    assert len(c.db.rows) == 2      # zen is blocklisted by default → nothing recorded
    assert c.current is None        # and it closed the open session


def test_blocklisted_zen_never_tracked():
    c = make_collector()
    c.poll_once({"class": "zen", "title": "private"}, (5, 5), t(0))
    assert c.current is None
    assert c.db.rows == []


def test_per_app_rule_overrides_blocklist_and_default():
    c = make_collector()
    c.poll_once({"class": "spotify", "title": "music"}, (5, 5), t(0))
    assert c.current is not None, "unknown apps are tracked by default"
    c.db.rules = {"spotify": False}  # user toggled it off in settings
    c.poll_once({"class": "spotify", "title": "music"}, (5, 5), t(20))
    assert c.current is None
    c.db.rules = {"spotify": True}
    c.poll_once({"class": "spotify", "title": "music"}, (5, 5), t(40))
    assert c.current is not None


def test_idle_stops_accrual():
    c = make_collector()
    win = {"class": "code", "title": "a"}
    c.poll_once(win, (5, 5), t(0))       # active, streak reset
    c.poll_once(win, (5, 5), t(20))      # still — streak 20s
    c.poll_once(win, (5, 5), t(40))      # streak 40s
    for i in range(1, 10):               # streak reaches 220s > 180s threshold
        c.poll_once(win, (5, 5), t(40 + i * 20))
    # time accrues through the idle grace period (until streak >= 180s),
    # i.e. up to t(160); the remaining still polls add nothing
    assert c.current["seconds"] == 160
    # cursor moves again → accrual resumes (elapsed 20s, cap 40s)
    c.poll_once(win, (6, 6), t(240))
    assert c.current["seconds"] == 180


def test_pause_stops_logging():
    c = make_collector()
    c.poll_once({"class": "code", "title": "a"}, (5, 5), t(0))
    c.set_paused(True)
    assert c.is_paused()
    assert c.current_session() is None
    c.step()  # paused: probe skipped, nothing new
    assert len(c.db.rows) == 1


def test_excluded_apps_skipped():
    c = make_collector()
    c.cfg.excluded_apps = "keepassxc"
    c.poll_once({"class": "keepassxc", "title": "Secrets"}, (5, 5), t(0))
    assert c.current is None
    assert c.db.rows == []


def test_suspend_gap_clamped():
    c = make_collector()
    win = {"class": "code", "title": "a"}
    c.poll_once(win, (5, 5), t(0))
    # 2 hours pass (laptop asleep), same window → only 40s credited
    c.poll_once(win, (5, 5), t(120))
    assert c.current["seconds"] == 40


def test_aggregate_day():
    sessions = [
        {"app_class": "code", "title": "a", "seconds": 600, "first_seen": "2026-09-30T10:00:00", "last_seen": "2026-09-30T10:10:00"},
        {"app_class": "code", "title": "b", "seconds": 300, "first_seen": "2026-09-30T10:10:00", "last_seen": "2026-09-30T10:15:00"},
        {"app_class": "zen", "title": "docs", "seconds": 60, "first_seen": "2026-09-30T10:15:00", "last_seen": "2026-09-30T10:16:00"},
    ]
    agg = aggregate_day(sessions)
    assert agg["total_seconds"] == 960
    assert agg["apps"][0]["app"] == "code"
    assert agg["apps"][0]["seconds"] == 900
    assert len(agg["sessions"]) == 3


def test_daily_log_fallback_and_transcript():
    sessions = [
        {"app_class": "code", "title": "fleeting — main.py", "seconds": 3600,
         "first_seen": "2026-09-30T09:00:00", "last_seen": "2026-09-30T10:00:00"},
        {"app_class": "zen", "title": "FastAPI docs", "seconds": 600,
         "first_seen": "2026-09-30T10:00:00", "last_seen": "2026-09-30T10:10:00"},
    ]
    transcript = build_transcript(sessions)
    assert "Time per app" in transcript and "code" in transcript
    assert "fleeting — main.py" in transcript
    md = fallback_digest(sessions, "2026-09-30")
    assert "# Daily Digest — 2026-09-30" in md
    assert "**code** (1h 00m)" in md
    assert "**09:00–10:00**" in md
    assert "fleeting — main.py" in md


def test_screentime_1hr_milestone_trigger():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone)
    today = c._today
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T11:00:00",
        "seconds": 3600,
        "day": today,
    })

    c.step()
    assert calls == [(today, 1)]
    assert c.db.kv_get(f"digest_screentime_hours_{today}") == "1"


def test_screentime_sub_1hr_no_trigger():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone)
    today = c._today
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T10:59:59",
        "seconds": 3599,
        "day": today,
    })

    c.step()
    assert calls == []
    assert c.db.kv_get(f"digest_screentime_hours_{today}") is None


def test_screentime_subsequent_1hr_triggers():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone)
    today = c._today
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T11:00:00",
        "seconds": 3600,
        "day": today,
    })
    c.step()
    assert calls == [(today, 1)]

    # Now add another hour to reach 7200s (2 hrs)
    c.db.rows.append({
        "id": 2,
        "app_class": "code",
        "title": "more work",
        "first_seen": f"{today}T11:00:00",
        "last_seen": f"{today}T12:00:00",
        "seconds": 3600,
        "day": today,
    })
    c.step()
    assert calls == [(today, 1), (today, 2)]
    assert c.db.kv_get(f"digest_screentime_hours_{today}") == "2"


def test_milestone_persisted_avoids_retrigger():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone)
    today = c._today
    c.db.kv_set(f"digest_screentime_hours_{today}", "1")
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T11:03:20",
        "seconds": 3800,
        "day": today,
    })

    c.step()
    assert calls == []
    assert c.db.kv_get(f"digest_screentime_hours_{today}") == "1"


def test_screentime_blocked_apps_excluded():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone)
    today = c._today
    # zen is blocked by default
    c.db.rows.append({
        "id": 1,
        "app_class": "zen",
        "title": "browsing",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T11:00:00",
        "seconds": 3600,
        "day": today,
    })
    c.step()
    assert calls == []
    assert c.today_screentime_seconds() == 0


def test_screentime_milestone_disabled_if_auto_daily_log_false():
    calls = []

    async def on_milestone(day: str, hours: int):
        calls.append((day, hours))

    c = make_collector(on_screentime_milestone=on_milestone, auto_daily_log=False)
    today = c._today
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{today}T10:00:00",
        "last_seen": f"{today}T11:00:00",
        "seconds": 3600,
        "day": today,
    })
    c.step()
    assert calls == []


def test_today_screentime_freshness_across_midnight():
    from fleeting.activity import _local_now
    c = make_collector()
    # Simulate collector started yesterday / stale _today
    c._today = "2020-01-01"
    actual_today = _local_now().strftime("%Y-%m-%d")

    # Add session for actual today
    c.db.rows.append({
        "id": 1,
        "app_class": "code",
        "title": "work",
        "first_seen": f"{actual_today}T10:00:00",
        "last_seen": f"{actual_today}T11:00:00",
        "seconds": 3600,
        "day": actual_today,
    })
    # today_screentime_seconds should evaluate for actual today, not the stale c._today
    assert c.today_screentime_seconds() == 3600



