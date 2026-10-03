# Assistant Action Execution & Hourly Screentime Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the "Ask Fleeting" assistant full agency to execute in-app tasks (delete/complete/create tasks, manage notes, trigger digests, pause activity) with live UI updates, and automatically generate/regenerate the Daily AI Executive Digest every 1 hour of screentime.

**Architecture:**
A unified Python action dispatcher (`backend/fleeting/services/actions.py`) exposes typed app tools which modify the SQLite database and publish SSE events to `st.bus` for instant UI updates. A dual execution pipeline in `backend/fleeting/services/assistant.py` detects direct user commands via a fast intent matcher for 0ms latency, while supporting model-driven structured action blocks (````action {...}````). `ActivityCollector` in `backend/fleeting/activity.py` detects when daily active screentime crosses each 1-hour boundary (3600s, 7200s, 10800s, etc.), triggering `generate_daily_log(rolling=True)` under an `asyncio.Lock` concurrency guard and persisting milestones in SQLite KV storage.

**Tech Stack:** Python 3.13, FastAPI, SQLite, SSE (Server-Sent Events), React, TypeScript, Vitest, Pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-assistant-actions-and-hourly-digest-design.md`

## Global Constraints
- Python backend test suite runs via `./backend/.venv/bin/pytest`.
- Frontend test suite runs via `npm test -- --run` in `frontend/`.
- All database operations must go through existing `Database` methods or atomic SQLite queries with appropriate commits.
- Actions that alter tasks or notes must publish their respective event (`task.created`, `task.updated`, `task.deleted`, `note.created`, `note.updated`, `note.deleted`, `dailylog.updated`) to `st.bus`.
- 1 hour of screentime is exactly 3600 seconds of active, non-blocked app sessions for the current day.

---

### Task 1: Action Dispatcher Service & Core Tools

**Files:**
- Create: `backend/fleeting/services/actions.py`
- Create: `backend/tests/test_actions.py`

**Interfaces:**
- Produces:
  - `execute_action(tool: str, params: dict, db: Database, cfg: Config, bus: EventBus) -> dict`
  - `AVAILABLE_ACTIONS: list[dict]`
  - Tools supported: `delete_tasks`, `create_task`, `toggle_task`, `update_task`, `create_note`, `delete_note`, `pin_note`, `generate_daily_digest`, `pause_activity`.

- [ ] **Step 1: Write failing unit test for `actions.py`**

In `backend/tests/test_actions.py`:
```python
import pytest
from fleeting.config import Config
from fleeting.db import Database
from fleeting.events import EventBus
from fleeting.services.actions import execute_action, AVAILABLE_ACTIONS

@pytest.fixture
def env(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.migrate()
    cfg = Config()
    bus = EventBus()
    return db, cfg, bus

def test_delete_all_tasks(env):
    db, cfg, bus = env
    t1 = db.insert_task({"text": "Task 1", "priority": "P1"})
    t2 = db.insert_task({"text": "Task 2", "priority": "P2"})
    assert len(db.list_tasks(status="all")) == 2

    events = []
    bus.subscribe("task.deleted", lambda data: events.append(data))

    res = execute_action("delete_tasks", {"all": True}, db, cfg, bus)
    assert res["ok"] is True
    assert res["count"] == 2
    assert len(db.list_tasks(status="all")) == 0
    assert len(events) == 2

def test_create_and_toggle_task(env):
    db, cfg, bus = env
    events = []
    bus.subscribe("task.created", lambda data: events.append(("created", data)))
    bus.subscribe("task.updated", lambda data: events.append(("updated", data)))

    res = execute_action("create_task", {"text": "Buy groceries", "priority": "P1"}, db, cfg, bus)
    assert res["ok"] is True
    task_id = res["task"]["id"]
    assert res["task"]["text"] == "Buy groceries"
    assert res["task"]["priority"] == "P1"

    toggle_res = execute_action("toggle_task", {"task_id": task_id}, db, cfg, bus)
    assert toggle_res["ok"] is True
    assert toggle_res["task"]["done"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./backend/.venv/bin/pytest backend/tests/test_actions.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'fleeting.services.actions')

- [ ] **Step 3: Implement `backend/fleeting/services/actions.py`**

Write `backend/fleeting/services/actions.py`:
- Implement `delete_tasks(params, db, cfg, bus)`
- Implement `create_task(params, db, cfg, bus)`
- Implement `toggle_task(params, db, cfg, bus)`
- Implement `update_task(params, db, cfg, bus)`
- Implement `create_note(params, db, cfg, bus)`
- Implement `delete_note(params, db, cfg, bus)`
- Implement `pin_note(params, db, cfg, bus)`
- Implement `generate_daily_digest(params, db, cfg, bus)`
- Implement `pause_activity(params, db, cfg, bus)`
- Implement `execute_action(tool, params, db, cfg, bus)`

- [ ] **Step 4: Run test to verify it passes**

Run: `./backend/.venv/bin/pytest backend/tests/test_actions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/fleeting/services/actions.py backend/tests/test_actions.py
git commit -m "feat(assistant): add core action execution service and tools"
```

---

### Task 2: Fast Intent Matcher & Action Execution in Assistant

**Files:**
- Modify: `backend/fleeting/services/assistant.py`
- Modify: `backend/fleeting/routers/assistant.py`
- Modify: `backend/tests/test_assistant_api.py`

**Interfaces:**
- Consumes: `execute_action` from `backend/fleeting/services/actions.py`
- Produces:
  - `match_fast_intent(query: str) -> tuple[str, dict] | None`
  - Assistant executes detected fast intents immediately or parses model ````action ... ```` blocks, executes them, updates DB/EventBus, and formats response.

- [ ] **Step 1: Write failing tests for fast intent and action execution in `backend/tests/test_assistant_api.py`**

Add tests:
- `test_assistant_fast_intent_delete_all_tasks`:
  Creates tasks, calls `ask_assistant(messages=[{"role": "user", "content": "delete all the tasks"}], ...)`
  Verifies tasks are deleted from `db`, result message confirms deletion, sources are provided.
- `test_assistant_fast_intent_generate_digest`:
  Calls `ask_assistant(messages=[{"role": "user", "content": "generate today's digest"}], ...)`
  Verifies `generate_daily_log` is invoked or scheduled and returns confirmation.
- `test_assistant_model_action_block_execution`:
  Simulates model output with:
  ````
  ```action
  {"tool": "delete_tasks", "parameters": {"all": true}}
  ```
  I have deleted all your active tasks.
  ````
  Verifies action block is executed, stripped from output, and database is updated.

- [ ] **Step 2: Run test to verify it fails**

Run: `./backend/.venv/bin/pytest backend/tests/test_assistant_api.py -k "test_assistant_fast_intent or test_assistant_model_action" -v`
Expected: FAIL

- [ ] **Step 3: Update `backend/fleeting/services/assistant.py` and `backend/fleeting/routers/assistant.py`**

1. Add `match_fast_intent(query: str) -> tuple[str, dict] | None`:
   - Match `"delete all tasks"`, `"delete all the tasks"`, `"clear all tasks"` -> `("delete_tasks", {"all": True})`
   - Match `"delete task <id>"`, `"remove task <id>"` -> `("delete_tasks", {"ids": [id]})`
   - Match `"mark task <id> as done"`, `"complete task <id>"` -> `("toggle_task", {"task_id": id})`
   - Match `"generate today's digest"`, `"create daily digest"` -> `("generate_daily_digest", {"rolling": True})`
   - Match `"pause activity"`, `"resume activity"` -> `("pause_activity", {"paused": ...})`
2. Update `ask_assistant`:
   - Accept optional `bus: EventBus | None = None`.
   - Check `match_fast_intent(user_query)`. If matched, execute via `execute_action(tool, params, db, cfg, bus)` and return clean conversational confirmation with sources.
   - Update system prompt with tool catalog and ````action ... ```` block instruction.
   - In LLM response parser: extract ````action ... ```` blocks, execute with `execute_action`, clean the response text, and return.
3. Update `backend/fleeting/routers/assistant.py` to pass `st.bus` to `ask_assistant`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./backend/.venv/bin/pytest backend/tests/test_assistant_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/fleeting/services/assistant.py backend/fleeting/routers/assistant.py backend/tests/test_assistant_api.py
git commit -m "feat(assistant): integrate fast intent matching and model action execution"
```

---

### Task 3: Automatic 1-Hour Screentime Digest Trigger

**Files:**
- Modify: `backend/fleeting/activity.py`
- Modify: `backend/fleeting/main.py`
- Modify: `backend/fleeting/routers/activity.py`
- Modify: `backend/tests/test_activity.py`

**Interfaces:**
- Produces:
  - `ActivityCollector.today_screentime_seconds() -> int`
  - `ActivityCollector.check_screentime_milestones(loop) -> None`
  - `on_screentime_milestone` callback in `main.py`
  - KV key: `digest_screentime_hours_{today}`

- [ ] **Step 1: Write failing tests in `backend/tests/test_activity.py`**

Add tests:
- `test_screentime_1hr_milestone_trigger`:
  Simulates sessions totaling 3600 seconds, calls step/milestone check, asserts `on_screentime_milestone` callback was called with `(today, 1)` and KV was set to `1`.
- `test_screentime_sub_1hr_no_trigger`:
  Simulates sessions totaling 3599 seconds, asserts callback not called.
- `test_screentime_subsequent_1hr_triggers`:
  Simulates sessions reaching 7200 seconds (2hr), asserts milestone 2 triggered.
- `test_milestone_persisted_avoids_retrigger`:
  With KV already set to `1` and total seconds 3800, asserts callback is NOT called again.

- [ ] **Step 2: Run test to verify it fails**

Run: `./backend/.venv/bin/pytest backend/tests/test_activity.py -k "milestone" -v`
Expected: FAIL

- [ ] **Step 3: Implement milestone tracking and runner**

1. In `backend/fleeting/activity.py`:
   - Add `on_screentime_milestone: Callable[[str, int], Awaitable[None]] | None = None` to `ActivityCollector.__init__`.
   - Add `today_screentime_seconds(self) -> int`.
   - Add `check_screentime_milestones(self, loop=None) -> None`.
   - Call `check_screentime_milestones(loop)` inside `step()`.
2. In `backend/fleeting/main.py`:
   - Create `digest_lock = asyncio.Lock()`.
   - Implement `generate_milestone_digest(day: str, hours: int)`:
     - Check if `digest_lock` is locked (skip if in progress).
     - Acquire lock, call `dailylog.generate_daily_log(db, cfg, day, rolling=True)`.
     - Publish `dailylog.updated` to `bus`.
   - Pass `generate_milestone_digest` as `on_screentime_milestone` to `ActivityCollector`.
3. In `backend/fleeting/routers/activity.py`:
   - When generating rolling daily log for today, sync `digest_screentime_hours_{today}` to `today_seconds // 3600`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./backend/.venv/bin/pytest backend/tests/test_activity.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/fleeting/activity.py backend/fleeting/main.py backend/fleeting/routers/activity.py backend/tests/test_activity.py
git commit -m "feat(activity): automatically generate executive digest every 1 hour of screentime"
```

---

### Task 4: UI Copy & Full Integration Verification

**Files:**
- Modify: `frontend/src/components/TimelineView.tsx`

**Interfaces:**
- Produces: Updated card empty-state text mentioning 1h automatic screentime generation.

- [ ] **Step 1: Update empty-state copy in `frontend/src/components/TimelineView.tsx`**

Update empty-state description:
`Synthesizes window sessions, modified files, and git commits into a daily briefing automatically every 1h of screentime and at midnight — or click Generate anytime.`

- [ ] **Step 2: Run frontend test suite**

Run: `npm test -- --run` in `frontend/`
Expected: ALL PASS

- [ ] **Step 3: Run full backend test suite**

Run: `./backend/.venv/bin/pytest`
Expected: ALL 180+ tests pass

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TimelineView.tsx
git commit -m "feat(frontend): update timeline executive digest description for hourly screentime triggers"
```

---
