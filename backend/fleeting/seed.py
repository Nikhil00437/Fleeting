"""#189 demo data.

Pinned ids and a pinned `today`, so #190 (Playwright) and #394 (visual
regression) can select a note by id and screenshot a known layout. Anything
sampled from `random` or stamped from the clock would make those tests flaky
for reasons that have nothing to do with the thing under test.

Deliberately imports nothing that migrates on import. `fleeting.main` builds
its app at module level, so touching it runs `migrate()` against the real
DB_PATH — the seeder has to stay usable from a fresh process pointed at a demo
XDG directory.

Every note is a *capture*, not a digest: `generated` stays 0, because #259 and
#260 read that column and a demo inbox full of AI-written summaries would
misrepresent the thing it is demonstrating.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Database

# The date the demo is written against. A fixed constant rather than
# `date.today()` — a demo whose contents shift every day is not a demo, and
# #394 needs the same layout on every run.
DEMO_TODAY = date(2026, 10, 11)

_APPS = ("code", "browser", "terminal", "chat", "docs", "media")

_PROJECTS = (
    ("homelab", "OpenWrt", "feat(firmware): add per-device throughput graph"),
    ("fleeting", "Fleeting", "fix(vault): keep generated notes out of urgency"),
    ("fleeting", "Fleeting", "test(seed): pin ids so visual regression is stable"),
    ("reading", None, None),
)


def _capture(i: int, day: date, hour: int) -> dict:
    """One note. The index is part of the id, so ordering never shifts."""
    return {
        "id": f"demo-note-{i:03d}",
        "type": ("text", "voice", "text", "youtube")[i % 4],
        "title": _TITLES[i % len(_TITLES)],
        "raw_text": _BODIES[i % len(_BODIES)],
        "summary": _SUMMARIES[i % len(_SUMMARIES)],
        "tags": list(_TAGS[i % len(_TAGS)]),
        # Pinned per note. `insert_note` promotes each item to a task row and
        # `new_id()`s it unless it carries an id, which would make two seeded
        # databases differ in both `tasks.id` and the JSON embedded here.
        "action_items": [
            {"id": f"demo-ai-{i:03d}-{n}", **item}
            for n, item in enumerate(_ACTIONS[i % len(_ACTIONS)])
        ],
        "confidence": 0.8,
        "created_at": f"{day.isoformat()}T{hour:02d}:{(i * 7) % 60:02d}:00+00:00",
        "pinned": 1 if i % 7 == 0 else 0,
        # Already enriched. A note left at the default `pending` is re-queued
        # on every boot by `Processor.recover_unfinished`, and with no LLM the
        # heuristic rewrites the title to the first 60 characters of the body —
        # which quietly replaced every seeded title with a body prefix.
        "status": "done",
    }


_TITLES = (
    "Router firmware upgrade failed halfway",
    "Talk outline: capture as you think",
    "OpenWrt per-device throughput",
    "Why the inbox never reaches zero",
    "Reading: The Design of Everyday Things",
    "Standup moved to 10:30",
    "yt-dlp subtitle extraction is flaky",
    "Calm down the enrich pass",
    "A week of captures, reviewed",
    "Fix: stuck process rows",
)

_BODIES = (
    "The upgrade stopped at 60% and left the device on the old image. Needs a\n"
    "recovery boot over serial before anything else.\n\nRemember to back up\n"
    "/etc/config first, that is what I skipped last time.",
    "Three acts. Capture is cheap and lossy. Enrichment is where the model\n"
    "sees it. Retrieval is where you find it again.\n\ntodo: write the opening\n"
    "example using the router note",
    "Built a small script to poll per-interface counters so the graph shows\n"
    "which device is actually saturating the uplink.\n\n- needs a persistent\n"
    "  rrd round the 1 minute mark\n- TODO: alert above 80% sustained",
    "It is not that there is too much to do, it is that triage never happens.\n"
    "Review on Friday, thirty minutes, no captures allowed.",
    "Chapter 6 on error is the one worth reading twice. The idea that most\n"
    "errors start as a slip rather than a mistake.",
    "Moving to 10:30 so it lands after the deploy window. Need to tell the\n"
    "standup channel and move the recurring event.",
    "Two runs produced an empty subtitle track and it did not raise. Checking\n"
    "the exit code fixes it.",
    "The enrich pass runs on every capture and re-asks for tags it just\n"
    "asked for. Batch it, or at least skip when the heuristic already agreed.",
    "Reviewed the week's captures. Twelve became tasks, three of those were\n"
    "duplicates. Dedup happens before the action items leave the note.",
    "Two processes stuck in running for four hours because the pid is reused.\n"
    "Poll the heartbeat instead.",
)

_SUMMARIES = (
    "The upgrade failed mid-flash and needs a serial recovery.",
    "A three-act structure for a talk about capture.",
    "Per-interface counters for finding uplink saturation.",
    "Triage never happens, so the inbox grows regardless of volume.",
    "Chapter 6 argues most errors are slips, not mistakes.",
    "Standup moved to 10:30 to sit after the deploy window.",
    "Empty subtitle tracks went unnoticed because the exit code was discarded.",
    "Enrichment re-asks for tags it already has.",
    "Three of twelve extracted tasks were duplicates.",
    "Stuck processes come from a reused pid, not a hung worker.",
)

_TAGS = (
    ["homelab", "router"],
    ["talk", "writing"],
    ["homelab", "metrics"],
    ["workflow"],
    ["reading"],
    ["work"],
    ["fleeting"],
    ["fleeting", "llm"],
    ["review"],
    ["fleeting", "bug"],
)

_ACTIONS = (
    [{"text": "Back up /etc/config before reflashing", "priority": "P1", "done": False}],
    [{"text": "Write the opening example from the router note", "priority": "P2", "done": False}],
    [{"text": "Persist the rrd round and alert above 80%", "priority": "P2", "done": False}],
    [{"text": "Friday review, thirty minutes, no captures", "priority": "P3", "done": False}],
    [],
    [{"text": "Tell the standup channel about 10:30", "priority": "P2", "done": True}],
    [{"text": "Check the yt-dlp exit code", "priority": "P1", "done": True}],
    [{"text": "Skip enrichment when the heuristic agrees", "priority": "P2", "done": False}],
    [{"text": "Dedup before action items leave the note", "priority": "P1", "done": False}],
    [{"text": "Poll a heartbeat rather than the pid", "priority": "P2", "done": True}],
)

# Added by hand rather than extracted from a capture, so a demo does not show
# the same task twice from two different paths.
_TASKS = (
    ("Replace the recovery image over serial", "P1", 0, "homelab"),
    ("Collect slide three's diagram", "P2", 0, None),
    ("Move the recurring standup event", "P3", 0, None),
    ("Add the per-device throughput graph", "P2", 0, "OpenWrt"),
    ("Cancel the unused analytics trial", "P3", 1, None),
    ("Buy a spare SD card", "P3", 1, None),
    ("Reply to Priya about the schema", "P2", 0, "fleeting"),
    ("Trim the enrichment timeout to 30s", "P2", 1, "fleeting"),
    ("Read chapter 6 twice", "P3", 1, None),
    ("Close out the stuck-process rows", "P1", 1, "fleeting"),
    ("Decide on the digest schedule", "P3", 0, None),
    ("Sketch the heatmap tooltip", "P3", 0, None),
)


def seed_demo(
    db: Database,
    *,
    days: int = 14,
    today: date = DEMO_TODAY,
) -> dict[str, int]:
    """Fill `db` with a plausible fortnight. Re-runnable.

    Fixed ids would normally mean a second run dies on the primary key, which
    is the wrong behaviour for a command a demo runs on the way to a
    screenshot. Skipping what is already there costs two queries and makes the
    script safe to re-run; it does mean `days` cannot shrink an existing
    dataset, which nothing needs.

    Returns the row counts actually written.
    """
    rng = random.Random(189)  # pinned: see the module docstring

    have_notes = {r["id"] for r in db.execute("SELECT id FROM notes").fetchall()}
    have_tasks = {r["id"] for r in db.execute("SELECT id FROM tasks").fetchall()}

    note_rows = []
    for i in range(days * 2):
        day = today - timedelta(days=i // 2)
        row = _capture(i, day, 8 + (i % 11))
        if row["id"] not in have_notes:
            db.insert_note(row)
            note_rows.append(row["id"])

    task_rows = []
    for i, (text, priority, done, repo) in enumerate(_TASKS):
        task_id = f"demo-task-{i:03d}"
        if task_id in have_tasks:
            continue
        day = today - timedelta(days=i % days)
        task = {
            "id": task_id,
            "text": text,
            "priority": priority,
            "done": done,
            "repo": repo,
            "note_id": (note_rows or ["demo-note-000"])[i % max(len(note_rows), 1)],
            "created_at": f"{day.isoformat()}T09:{(i * 11) % 60:02d}:00+00:00",
            # A completed task stamped at creation would put its finish before
            # its start whenever the offset wraps; +3h never does.
            "completed_at": f"{day.isoformat()}T12:00:00+00:00" if done else None,
        }
        db.insert_task(task)
        task_rows.append(task_id)

    # `upsert_activity` only updates when handed an existing `id`, and
    # `activity.id` is a rowid — pinning one would collide with organically
    # collected sessions. Keyed on (day, first_seen) instead, which is
    # deterministic here because every timestamp is generated.
    have_activity = {
        (r["day"], r["first_seen"])
        for r in db.execute("SELECT day, first_seen FROM activity").fetchall()
    }

    activity = 0
    for d in range(days):
        day = today - timedelta(days=d)
        # Between three and six blocks a day. The variance matters: a demo
        # where every day is identical hides exactly the layout problems #394
        # is supposed to catch.
        for block in range(rng.randint(3, 6)):
            start = 9 * 3600 + block * 2700 + rng.randint(0, 900)
            end = start + rng.randint(600, 3000)
            first_seen = f"{day.isoformat()}T{_hms(start)}"
            if (day.isoformat(), first_seen) in have_activity:
                continue
            project, repo, _ = _PROJECTS[(d + block) % len(_PROJECTS)]
            db.upsert_activity(
                {
                    "app_class": _APPS[(d + block) % len(_APPS)],
                    "title": f"{project} — session {block + 1}",
                    "first_seen": first_seen,
                    "last_seen": f"{day.isoformat()}T{_hms(end)}",
                    "seconds": end - start,
                    "day": day.isoformat(),
                    "project": project,
                    "repo": repo,
                    "branch": "main",
                    "idle_secs": 0,
                }
            )
            activity += 1

    db.commit()
    return {
        "notes": len(note_rows),
        "tasks": len(task_rows),
        "activity": activity,
    }


def _hms(seconds_from_midnight: int) -> str:
    h, rem = divmod(seconds_from_midnight, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"