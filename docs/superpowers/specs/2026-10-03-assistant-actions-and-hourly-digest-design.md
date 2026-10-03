# Assistant Action Execution Engine & Hourly Screentime Digest Design

## 1. Overview
This design covers two interconnected capabilities for Fleeting:
1. **App Action Execution Engine for "Ask Fleeting"**: Transforms the assistant from a read-only RAG assistant into an agent that can perform any user action in the app (deleting tasks, completing tasks, creating notes/tasks, updating priorities, triggering digests, pausing activity logging) with immediate execution, live UI updates via SSE, and offline fallback.
2. **Automatic 1-Hour Screentime Digest Generation**: Automatically generates the Daily AI Executive Digest when total screentime for today reaches 1 hour (3600 seconds), and regenerates it whenever an additional 1 hour is accumulated (2h, 3h, 4h, etc.).

## 2. Architecture & Data Flow

```
                      +-----------------------------+
                      |       Ask Fleeting          |
                      |   (User Chat Interface)     |
                      +--------------+--------------+
                                     |
                                     v
                        /api/assistant/chat
                                     |
                                     v
                       +-------------+-------------+
                       | Fast Intent Classifier    |
                       +-------------+-------------+
                        /                         \
         [Matched direct command]         [General / Nuanced query]
                      /                             \
                     v                               v
         Execute Action Directly           LLM with Action Tools Prompt
                     \                               /
                      \               [Parsed ```action {...}``` block]
                       \                             /
                        v                           v
                      +-------------------------------+
                      |      Action Dispatcher        |
                      |  (backend/services/actions.py)|
                      +---------------+---------------+
                                      |
                    +-----------------+-----------------+
                    |                                   |
                    v                                   v
             Database Updates                    EventBus Publish
         (SQLite: tasks, notes, etc.)       (bus.publish -> SSE /api/events)
                    |                                   |
                    +-----------------+-----------------+
                                      |
                                      v
                             Frontend Live Sync
                          (Tasks, Notes, Timeline)
```

## 3. Component Details

### 3.1 App Actions Dispatcher (`backend/fleeting/services/actions.py`)
A unified, typed service for executing actions:

* **Task Actions**:
  - `delete_tasks(ids=None, all=False, status=None, repo=None)`:
    - If `all=True`: deletes all tasks in the database matching status/repo filters.
    - If `ids` provided: deletes specific task IDs.
    - Publishes `task.deleted` for each task and updates parent notes.
  - `create_task(text, priority="P2", due_date=None, repo=None, note_id=None)`:
    - Inserts task, publishes `task.created`.
  - `toggle_task(task_id)`:
    - Toggles done status, publishes `task.updated`.
  - `update_task(task_id, ...)`:
    - Updates text, priority, due date, or repo, publishes `task.updated`.

* **Note Actions**:
  - `create_note(content, title=None, tags=None)`:
    - Creates note, syncs to vault, publishes `note.created`.
  - `delete_note(note_id)`:
    - Deletes note and associated tasks, publishes `note.deleted`.
  - `pin_note(note_id, pinned)`:
    - Toggles pin state, publishes `note.updated`.

* **Activity & Digest Actions**:
  - `generate_daily_digest(day=None, rolling=True)`:
    - Triggers `dailylog.generate_daily_log`, publishes `dailylog.updated`.
  - `pause_activity(paused)`:
    - Pauses/resumes window tracking, publishes `activity.live`.

### 3.2 Fast Intent Routing & LLM Action Execution (`backend/fleeting/services/assistant.py`)
* **Fast Intent Matcher**:
  - Regular expression patterns for direct user commands:
    - Delete tasks: `r"^(?:delete|remove|clear)\s+(?:all\s+(?:the\s+)?)?tasks?"`
    - Toggle/complete task: `r"^(?:mark|set|toggle)\s+(?:task\s+)?(?:\[\[task:(?P<id>[^|]+)\|[^\]]+\]\]|(?P<id2>\S+))\s+(?:as\s+)?(?:done|complete)"`
    - Generate digest: `r"^(?:generate|create|update|refresh)\s+(?:today'?s?\s+)?(?:ai\s+)?(?:executive\s+)?digest"`
    - Pause/resume logging: `r"^(?:pause|stop|resume|start)\s+(?:activity\s+)?(?:logging|tracking)"`
  - Immediately executes without local LLM delay and responds with formatted confirmation.

* **Model Action Specification**:
  - The system prompt explains available actions and the format:
    ````markdown
    ```action
    {"tool": "delete_tasks", "parameters": {"all": true}}
    ```
    ````
  - The response parser extracts ````action ... ```` blocks, executes the tool, replaces the block with a natural confirmation (or incorporates the result into the reply), and returns the updated state.

### 3.3 Hourly Screentime Automatic Digest (`backend/fleeting/activity.py` & `main.py`)
* **Milestone Calculation**:
  - `total_seconds = sum(s["seconds"] for s in db.activity_sessions(today) if not app_blocked(...))`
  - `hours = total_seconds // 3600`
  - Reads `last_milestone = int(db.kv_get(f"digest_screentime_hours_{today}", "0"))`
  - If `hours >= 1` and `hours > last_milestone`:
    - Sets `db.kv_set(f"digest_screentime_hours_{today}", str(hours))`
    - Calls `on_screentime_milestone(today, hours)`
* **Execution & Concurrency Guard**:
  - In `backend/fleeting/main.py`, `generate_milestone_digest` uses an `asyncio.Lock()` to prevent concurrent overlapping runs.
  - Calls `await dailylog.generate_daily_log(db, cfg, day, rolling=True)`.
  - Emits `dailylog.updated` (pushes to frontend via SSE) and sends desktop notification.
  - When user manually generates a digest or asks assistant to generate it, the milestone is synced to current `hours` to prevent duplicate regeneration.

### 3.4 UI Copy Update (`frontend/src/components/TimelineView.tsx`)
* Updates helper description to reflect that digests generate automatically every 1h of screentime and at midnight.

## 4. Testing & Verification Plan
1. **Actions Service Unit Tests (`backend/tests/test_actions.py`)**:
   - `test_delete_all_tasks`: Creates multiple tasks, invokes action, verifies tasks deleted and events published.
   - `test_create_and_toggle_task`: Verifies creation, field population, and completion toggles.
   - `test_delete_note_and_cascade`: Verifies note deletion and task cascading.
   - `test_fast_intent_matcher`: Validates regex matches for commands like "delete all the tasks", "generate digest", etc.
2. **Assistant Action Integration Tests (`backend/tests/test_assistant_api.py`)**:
   - Test assistant chat with "delete all the tasks" executes action and returns success message.
   - Test LLM response containing ````action ... ```` block parses, executes, and cleans output.
3. **Hourly Screentime Trigger Tests (`backend/tests/test_activity.py`)**:
   - Test collector with 3600s screentime triggers 1h milestone.
   - Test collector advancing from 3600s to 7200s triggers 2h milestone.
   - Test collector at 7199s does not trigger milestone 2.
   - Test milestone persistence across restarts.
4. **Full Regression Suite**:
   - Run backend `pytest` and frontend `vitest`.
