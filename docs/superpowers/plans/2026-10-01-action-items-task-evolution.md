# Action Items & Task Management Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve Fleeting's task management system into a developer-first task system with a dedicated relational `tasks` SQLite table, AI/heuristic extraction of priorities (P1–P3), due dates, and repo tags, atomic REST endpoints, and an interactive Task Workbench UI.

**Architecture:** A dedicated SQLite `tasks` table with foreign key cascading and multi-column indexes replaces embedded JSON arrays for task operations while maintaining bidirectional synchronization with `notes.action_items` for Obsidian Markdown vault compatibility. The local LLM and regex fallback extract priorities, dates, and repositories. A dedicated `/api/tasks` FastAPI router provides atomic endpoints, and `TasksView.tsx` provides multi-facet filtering and direct manipulation.

**Tech Stack:** Python 3.13, FastAPI, SQLite3, Pydantic, TypeScript, React 19, Tailwind CSS, Vite, Vitest, Pytest.

**Spec:** [`docs/superpowers/specs/2026-10-01-action-items-task-evolution-design.md`](file:///home/nikhil/Projects/fleeting/docs/superpowers/specs/2026-10-01-action-items-task-evolution-design.md)

## Global Constraints

- Backend platform: Linux / Python 3.13 (`uv run pytest` for testing).
- Database: SQLite3 in WAL mode (`backend/fleeting/db.py`), zero data loss migration.
- Task Priorities: Strict enum `'P1'` (Urgent/Blocker), `'P2'` (Normal), `'P3'` (Low/Someday).
- Due Dates: Standard ISO format `'YYYY-MM-DD'` or `None`.
- Repository Tags: Lowercase string or `None`, matched against discovered local git directories under `watch_dirs`.
- Backward Compatibility: `notes.action_items` and Markdown vault sync MUST stay updated whenever tasks mutate.
- Frontend: React 19 + TypeScript + Vitest (`npm test` in `frontend/`).

---

### Task 1: Database Schema, Relational CRUD & Migration

**Files:**
- Modify: `backend/fleeting/db.py`
- Modify: `backend/fleeting/models.py`
- Test: `backend/tests/test_tasks_db.py`

**Interfaces:**
- Consumes: `notes` table, `now_iso()`, `new_id()`.
- Produces:
  - `Database.insert_task(task: dict) -> dict`
  - `Database.get_task(task_id: str) -> dict | None`
  - `Database.update_task(task_id: str, changes: dict) -> dict | None`
  - `Database.toggle_task(task_id: str) -> dict | None`
  - `Database.delete_task(task_id: str) -> dict | None`
  - `Database.list_tasks(status="open", priority=None, repo=None, due=None, q=None, limit=200, offset=0) -> list[dict]`
  - `Database.task_stats() -> dict`
  - `Database.task_repos() -> list[dict]`
  - `Database._sync_note_action_items(note_id: str) -> None`

- [ ] **Step 1: Write the failing tests in `backend/tests/test_tasks_db.py`**
  - Verify `tasks` table creation on DB init.
  - Verify migration from `notes.action_items` JSON strings on startup.
  - Verify task CRUD (`insert_task`, `update_task`, `toggle_task`, `delete_task`).
  - Verify `list_tasks` filtering by status (`open`, `done`, `all`), priority (`P1`, `P2`, `P3`), and repo.
  - Verify bidirectional synchronization between `tasks` table and `notes.action_items`.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run: `cd backend && uv run pytest tests/test_tasks_db.py`

- [ ] **Step 3: Update `backend/fleeting/models.py`**
  - Update `ActionItem`: add `priority: str = "P2"`, `due_date: str | None = None`, `repo: str | None = None`, `completed_at: str | None = None`.
  - Add `TaskOut`: schema matching `ActionItem` plus `note_id: str`, `note_title: str`, `created_at: str`.
  - Add `TaskCreateIn` and `TaskUpdateIn` schemas.

- [ ] **Step 4: Implement schema, migration & CRUD in `backend/fleeting/db.py`**
  - Add `CREATE TABLE IF NOT EXISTS tasks` and indexes (`note_id`, `done`, `priority`, `due_date`, `repo`).
  - Implement idempotent `_migrate_action_items()` on database startup.
  - Implement `insert_task`, `get_task`, `update_task`, `toggle_task`, `delete_task`, `list_tasks`, `task_stats`, and `task_repos`.
  - Implement `_sync_note_action_items(note_id)` to keep `notes.action_items` aligned.

- [ ] **Step 5: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_tasks_db.py`

- [ ] **Step 6: Commit**
  - `git add backend/fleeting/db.py backend/fleeting/models.py backend/tests/test_tasks_db.py`
  - `git commit -m "feat(db): implement relational tasks table, migration, and note sync"`

---

### Task 2: Task Extraction, Enrichment & Local Repo Discovery

**Files:**
- Create: `backend/fleeting/services/repos.py`
- Modify: `backend/fleeting/services/llm.py`
- Modify: `backend/fleeting/process.py`
- Test: `backend/tests/test_tasks_enrich.py`

**Interfaces:**
- Consumes: `backend/fleeting/db.py` task methods from Task 1.
- Produces:
  - `services/repos.py:discover_git_repos(watch_dirs: str) -> list[dict]`
  - `services/llm.py:enrich(text, cfg)` returning structured `action_items` with `{text, priority, due_date, repo}`
  - `services/llm.py:heuristic_enrich(text)` extracting `{text, priority, due_date, repo}`
  - `process.py` creating tasks in SQLite `tasks` table and syncing `notes.action_items`.

- [ ] **Step 1: Write failing tests in `backend/tests/test_tasks_enrich.py`**
  - Test `discover_git_repos` scanning directory paths for `.git`.
  - Test `heuristic_enrich` extracting P1 from "urgent / asap", P3 from "someday / low-priority", dates from "by tomorrow", and repo from "in fleeting repo".
  - Test LLM `_sanitize` normalizing structured action items.
  - Test `Processor._process` inserting extracted items into `tasks` table.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run: `cd backend && uv run pytest tests/test_tasks_enrich.py`

- [ ] **Step 3: Implement `backend/fleeting/services/repos.py`**
  - Scan comma-separated directories in `watch_dirs` (e.g. `~/Projects`).
  - Detect git worktrees (`.git` file or dir).
  - Return sorted list of `{"name": str, "path": str}`.

- [ ] **Step 4: Update `backend/fleeting/services/llm.py`**
  - Update `ENRICH_SCHEMA` with `{text, priority, due_date, repo}`.
  - Inject current ISO date context in system prompt.
  - Update `heuristic_enrich` regex pattern matching for priority, due dates, and repos.
  - Update `_sanitize` to handle both legacy strings and new object dicts.

- [ ] **Step 5: Update `backend/fleeting/process.py`**
  - In `Processor._process`, insert action items into `tasks` table using `self.db.insert_task`.
  - Attach detected active repo context if available from note source metadata.

- [ ] **Step 6: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_tasks_enrich.py`

- [ ] **Step 7: Commit**
  - `git add backend/fleeting/services/repos.py backend/fleeting/services/llm.py backend/fleeting/process.py backend/tests/test_tasks_enrich.py`
  - `git commit -m "feat(enrich): add structured task extraction, heuristic rules, and git repo discovery"`

---

### Task 3: Dedicated Task REST API & SSE Events

**Files:**
- Create: `backend/fleeting/routers/tasks.py`
- Modify: `backend/fleeting/main.py`
- Modify: `backend/fleeting/routers/search.py`
- Test: `backend/tests/test_tasks_api.py`

**Interfaces:**
- Consumes: `db` task methods from Task 1, `services/repos.py` from Task 2.
- Produces:
  - `GET /api/tasks`
  - `POST /api/tasks`
  - `GET /api/tasks/{task_id}`
  - `PATCH /api/tasks/{task_id}`
  - `POST /api/tasks/{task_id}/toggle`
  - `DELETE /api/tasks/{task_id}`
  - `GET /api/tasks/repos`
  - `GET /api/tasks/stats`
  - SSE events: `task.created`, `task.updated`, `task.deleted`

- [ ] **Step 1: Write failing tests in `backend/tests/test_tasks_api.py`**
  - Test `GET /api/tasks` with status, priority, and repo filters.
  - Test `POST /api/tasks/{task_id}/toggle` toggling status and broadcasting `task.updated`.
  - Test `PATCH /api/tasks/{task_id}` updating priority and due date.
  - Test `POST /api/tasks` creating standalone task.
  - Test `DELETE /api/tasks/{task_id}` removing task and broadcasting `task.deleted`.
  - Test `GET /api/tasks/repos` and `GET /api/tasks/stats`.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run: `cd backend && uv run pytest tests/test_tasks_api.py`

- [ ] **Step 3: Implement `backend/fleeting/routers/tasks.py`**
  - Define router with prefix `/api/tasks`.
  - Wire up CRUD endpoints, toggle, repos, and stats endpoints.
  - Broadcast SSE events via `st.bus.publish`.
  - Re-sync note action items on every mutation.

- [ ] **Step 4: Register router in `backend/fleeting/main.py`**
  - Import and include `tasks.router`.

- [ ] **Step 5: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_tasks_api.py`
  - Run full backend suite: `cd backend && uv run pytest`

- [ ] **Step 6: Commit**
  - `git add backend/fleeting/routers/tasks.py backend/fleeting/main.py backend/fleeting/routers/search.py backend/tests/test_tasks_api.py`
  - `git commit -m "feat(api): add dedicated tasks router with atomic toggle, filtering, and SSE events"`

---

### Task 4: Frontend API Client, Types & Task Workbench UI Overhaul

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/TasksView.tsx`
- Modify: `frontend/src/index.css`
- Test: `frontend/src/components/__tests__/TasksView.test.tsx`

**Interfaces:**
- Consumes: Task REST endpoints from Task 3 (`/api/tasks`, `/api/tasks/{id}/toggle`, `/api/tasks/repos`, etc.).
- Produces:
  - `TaskItem`, `TaskPriority`, `TaskStats`, `RepoInfo` in `types.ts`.
  - `api.tasks()`, `api.toggleTask()`, `api.updateTask()`, `api.deleteTask()`, `api.createTask()`, `api.taskRepos()`, `api.taskStats()`.
  - Redesigned `TasksView.tsx` with multi-facet filter chips, grouping modes (`Stream`, `By Priority`, `By Note`), direct priority/date popovers, and inline text editing.

- [ ] **Step 1: Write failing frontend tests in `frontend/src/components/__tests__/TasksView.test.tsx`**
  - Test rendering task items with priority badges (`P1`, `P2`, `P3`), due dates, and repo pills.
  - Test status tabs (`Open`, `Completed`, `All`) and priority filter chips (`P1`, `P2`, `P3`).
  - Test one-tap task toggle calling `api.toggleTask`.
  - Test priority cycle / change calling `api.updateTask`.
  - Test grouping by priority displaying separate priority bands.

- [ ] **Step 2: Update `frontend/src/types.ts` and `frontend/src/api.ts`**
  - Add `TaskPriority` (`"P1" | "P2" | "P3"`), `TaskItem`, `TaskStats`, `RepoInfo`.
  - Add API methods: `tasks(params)`, `toggleTask(id)`, `updateTask(id, data)`, `createTask(data)`, `deleteTask(id)`, `taskRepos()`, `taskStats()`.

- [ ] **Step 3: Update `frontend/src/index.css`**
  - Add styling classes for priority badges (`.badge-p1`, `.badge-p2`, `.badge-p3`), due date pills (`.due-overdue`, `.due-today`, `.due-soon`), and repo chips.

- [ ] **Step 4: Implement interactive controls & grouping in `frontend/src/components/TasksView.tsx`**
  - Add Priority filter chips (`All`, `P1`, `P2`, `P3`) and Due Date filter chips (`All`, `Overdue`, `Today`, `This Week`).
  - Add Repo dropdown filter populated from `api.taskRepos()`.
  - Add Grouping mode toggle: `Stream` (linear sorted), `By Priority` (sections for P1, P2, P3), and `By Note`.
  - Enhance task row with:
    - Interactive priority pill (click to toggle P1/P2/P3).
    - Relative due date badge with quick picker popover.
    - Repo tag pill.
    - Inline editable title.
    - Optimistic toggle with `api.toggleTask`.
  - Upgrade inline task creator to support quick priority and repo selection.

- [ ] **Step 5: Run tests and build**
  - Run: `cd frontend && npm test`
  - Run: `cd frontend && npm run build`

- [ ] **Step 6: Commit**
  - `git add frontend/src/types.ts frontend/src/api.ts frontend/src/components/TasksView.tsx frontend/src/index.css frontend/src/components/__tests__/TasksView.test.tsx`
  - `git commit -m "feat(ui): overhaul TasksView with multi-facet filters, priority popovers, and grouping modes"`
