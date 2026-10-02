# Obsidian & Markdown Vault 2-Way Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement full two-way synchronization between Fleeting's SQLite database and Obsidian/Markdown vault directories, supporting real-time task checkbox toggles, title/tag/content edits, importing new markdown files, and content-addressed echo suppression to prevent write feedback loops.

**Architecture:** A real-time `watchdog` inotify observer in the FastAPI backend monitors `cfg.paths.vault_dir`. A thread-safe `VaultSyncRegistry` tracks SHA-256 hashes of Fleeting-written files to drop self-write echoes. When external edits occur, `services/markdown.py` parses frontmatter, headings, and checklist items (including `[P1]`, `[due:...]`, `[repo:...]` metadata tags), reconciles them against SQLite `notes` and `tasks` tables, and emits live SSE events on `EventBus`. `POST /api/settings/vault/resync` and `SettingsView.tsx` provide on-demand reconciliation and live watcher telemetry.

**Tech Stack:** Python 3.13, FastAPI, SQLite3, Watchdog, Pydantic, TypeScript, React 19, Tailwind CSS, Vite, Vitest, Pytest.

**Spec:** [`docs/superpowers/specs/2026-10-02-obsidian-markdown-vault-sync-design.md`](file:///home/nikhil/Projects/fleeting/docs/superpowers/specs/2026-10-02-obsidian-markdown-vault-sync-design.md)

## Global Constraints

- Backend platform: Linux / Python 3.13 (`uv run pytest` for testing).
- Real-time watcher: `watchdog>=4.0` in `backend/pyproject.toml`.
- Echo suppression: Thread-safe SHA-256 hash tracking with 10-second TTL to eliminate infinite write loops.
- Event debouncing: 400ms buffer per file to handle atomic editor saves.
- Markdown checklists: `- [ ]` (open), `- [x]` or `- [X]` (done). Metadata tags formatted as `[P1]`, `[due:YYYY-MM-DD]`, `[repo:name]`.
- Non-destructive sync: Deleting a file in the vault archives the note (`archived = 1`) rather than permanently deleting SQLite records.
- Backward compatibility: Existing `sync_note`, `remove_note`, and `render_note_md` signatures must remain supported.
- Frontend: React 19 + TypeScript + Vitest (`npm test` in `frontend/`).

---

### Task 1: Smart Markdown Parser & Metadata Formatter

**Files:**
- Modify: `backend/fleeting/services/markdown.py`
- Test: `backend/tests/test_markdown_parser.py`

**Interfaces:**
- Consumes: `note` dict structure from `backend/fleeting/models.py`.
- Produces:
  - `parse_note_md(content: str) -> dict` returning:
    - `id`: `str | None`
    - `title`: `str`
    - `summary`: `str`
    - `tags`: `list[str]`
    - `action_items`: `list[dict]` with `{id, text, done, priority, due_date, repo}`
    - `raw_text`: `str`
    - `source`: `dict`
    - `type`: `str`
  - Enhanced `render_note_md(note: dict) -> str` formatting metadata tags on checklist items.

- [ ] **Step 1: Write failing tests in `backend/tests/test_markdown_parser.py`**
  - Test `render_note_md` formats `[P1]`, `[due:2026-10-05]`, `[repo:fleeting]` tags on checklist items.
  - Test `parse_note_md` parses YAML frontmatter (`id`, `type`, `created`, `tags`, `source`).
  - Test `parse_note_md` extracts title from first `# Heading`.
  - Test `parse_note_md` extracts checklist items with `- [ ]` (done=False) and `- [x]` (done=True).
  - Test `parse_note_md` extracts metadata tags `[P1]`, `[due:YYYY-MM-DD]`, `[repo:name]`, and strips them from task `text`.
  - Test `parse_note_md` handles files without frontmatter or subheadings.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run: `cd backend && uv run pytest tests/test_markdown_parser.py`

- [ ] **Step 3: Implement `parse_note_md` and update `render_note_md` in `backend/fleeting/services/markdown.py`**
  - In `render_note_md`: include `[P1]`/`[P3]`, `[due:YYYY-MM-DD]`, and `[repo:name]` on checklist items if present.
  - Implement `parse_note_md`:
    - Regex / line-by-line parsing for frontmatter between `---`.
    - Extract title, summary, action items with checklist regex `r"^[ \t]*-[ \t]*\[([ xX])\][ \t]+(.*)$"`.
    - Extract and strip tags `\[(P[123])\]`, `\[due:(\d{4}-\d{2}-\d{2})\]`, and `\[repo:([a-zA-Z0-9_-]+)\]`.
    - Extract content under `## Content` or `## Transcript`.

- [ ] **Step 4: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_markdown_parser.py`
  - Run full backend suite: `cd backend && uv run pytest`

- [ ] **Step 5: Commit**
  - `git add backend/fleeting/services/markdown.py backend/tests/test_markdown_parser.py`
  - `git commit -m "feat(markdown): implement bidirectional parser and task metadata serialization"`

---

### Task 2: Watchdog Observer & Echo Suppression Engine

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/fleeting/services/vault_watcher.py`
- Modify: `backend/fleeting/services/markdown.py`
- Test: `backend/tests/test_vault_watcher.py`

**Interfaces:**
- Consumes: `watchdog`, `PathsConfig` from `backend/fleeting/config.py`.
- Produces:
  - `VaultSyncRegistry`: `register(path, content)`, `is_echo(path, content) -> bool`, `clear()`.
  - `VaultWatcher`:
    - `start() -> None`
    - `stop() -> None`
    - `is_running() -> bool`
    - Debounced event queue dispatching file paths to a sync callback.
  - Global `sync_registry` integrated into `services/markdown.py:sync_note(...)`.

- [ ] **Step 1: Add `watchdog>=4.0` to `backend/pyproject.toml`**
  - Run: `cd backend && uv add watchdog`
  - Verify import: `cd backend && uv run python -c "import watchdog"`

- [ ] **Step 2: Write failing tests in `backend/tests/test_vault_watcher.py`**
  - Test `VaultSyncRegistry.register` records content SHA-256 and `is_echo` returns `True`.
  - Test `VaultSyncRegistry.is_echo` returns `False` for modified content.
  - Test `VaultWatcher` starts, stops, and debounces file system events for `.md` files.

- [ ] **Step 3: Implement `VaultSyncRegistry` and `VaultWatcher` in `backend/fleeting/services/vault_watcher.py`**
  - Thread-safe `VaultSyncRegistry` with SHA-256 caching and 10s TTL.
  - `VaultWatcher` using `watchdog.observers.Observer` and `FileSystemEventHandler`.
  - Filter for `.md` files; ignore dotfiles and temporary editor extensions (`.tmp`, `.swp`).
  - Thread-safe debounce timer (400ms) before dispatching callback.

- [ ] **Step 4: Connect `VaultSyncRegistry` to `markdown.sync_note`**
  - When `markdown.sync_note` writes a file to disk, register the path and content with `sync_registry`.

- [ ] **Step 5: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_vault_watcher.py`

- [ ] **Step 6: Commit**
  - `git add backend/pyproject.toml backend/uv.lock backend/fleeting/services/vault_watcher.py backend/fleeting/services/markdown.py backend/tests/test_vault_watcher.py`
  - `git commit -m "feat(vault): add watchdog observer and content-addressed echo suppression"`

---

### Task 3: Ingestion Logic, FastAPI Lifecycle & Resync API

**Files:**
- Modify: `backend/fleeting/services/vault_watcher.py`
- Modify: `backend/fleeting/main.py`
- Modify: `backend/fleeting/routers/settings.py`
- Test: `backend/tests/test_vault_sync.py`

**Interfaces:**
- Consumes: `Database`, `EventBus`, `VaultWatcher`, `parse_note_md`.
- Produces:
  - `VaultWatcher.handle_file_change(path: Path) -> dict | None`
  - `VaultWatcher.resync_all() -> dict`
  - FastAPI lifespan auto-start of `VaultWatcher` when `vault_sync` enabled.
  - `POST /api/settings/vault/resync` endpoint returning `{ok: true, synced_notes, imported_notes, tasks_updated}`.

- [ ] **Step 1: Write failing tests in `backend/tests/test_vault_sync.py`**
  - Test editing an existing note file: checklist toggles update task `done` & `completed_at` in DB and emit SSE.
  - Test adding a new checklist item in Markdown inserts task into SQLite.
  - Test modifying title/tags in Markdown updates note in SQLite.
  - Test dropping a new Markdown file without frontmatter creates a new note in SQLite and adds `id:` to frontmatter.
  - Test `POST /api/settings/vault/resync` reconciles all notes in the vault.

- [ ] **Step 2: Run pytest to confirm tests fail**
  - Run: `cd backend && uv run pytest tests/test_vault_sync.py`

- [ ] **Step 3: Implement ingestion logic in `backend/fleeting/services/vault_watcher.py`**
  - When non-echo event arrives:
    - Parse with `parse_note_md`.
    - If `id` in frontmatter and note exists in DB:
      - Update note fields (`title`, `tags`, `raw_text`, `summary`) if changed.
      - Reconcile tasks: update `done`, `completed_at`, `priority`, `due_date`, `repo`; insert new tasks; delete removed tasks.
      - Sync note `action_items` in SQLite (`_sync_note_action_items`).
      - Emit `note.updated` and `task.updated` on EventBus.
    - If no `id` (or not in DB):
      - Create note via `db.insert_note`.
      - Insert tasks into `tasks` table.
      - Write back frontmatter to file with generated `id`, registering hash in `VaultSyncRegistry`.
      - Emit `note.created` and `task.created` on EventBus.
  - Implement `resync_all()` method scanning all `.md` files in `vault_dir`.

- [ ] **Step 4: Wire FastAPI lifespan and router endpoint**
  - In `backend/fleeting/main.py`: initialize and start `st.vault_watcher` during startup if `cfg.paths.vault_sync` is enabled; stop on shutdown.
  - In `backend/fleeting/routers/settings.py`: add `POST /api/settings/vault/resync` calling `st.vault_watcher.resync_all()`.

- [ ] **Step 5: Run tests and verify 100% pass**
  - Run: `cd backend && uv run pytest tests/test_vault_sync.py`
  - Run full backend suite: `cd backend && uv run pytest`

- [ ] **Step 6: Commit**
  - `git add backend/fleeting/services/vault_watcher.py backend/fleeting/main.py backend/fleeting/routers/settings.py backend/tests/test_vault_sync.py`
  - `git commit -m "feat(vault): implement bidirectional ingestion, lifespan lifecycle, and resync API"`

---

### Task 4: Frontend Settings View Status Pill & Force Re-sync Action

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/SettingsView.tsx`
- Test: `frontend/src/components/__tests__/SettingsView.test.tsx`

**Interfaces:**
- Consumes: `POST /api/settings/vault/resync` from Task 3.
- Produces:
  - `VaultSyncResult` in `frontend/src/types.ts`.
  - `api.resyncVault(): Promise<VaultSyncResult>` in `frontend/src/api.ts`.
  - Settings UI Obsidian card with live watcher status pill and "Force Vault Re-sync" button.

- [ ] **Step 1: Write failing frontend test in `frontend/src/components/__tests__/SettingsView.test.tsx`**
  - Test rendering vault sync status badge ("Watching Vault" when enabled).
  - Test clicking "Force Vault Re-sync" invokes `api.resyncVault()` and displays summary toast.

- [ ] **Step 2: Update `frontend/src/types.ts` and `frontend/src/api.ts`**
  - Add `VaultSyncResult`: `{ ok: boolean, synced_notes: number, imported_notes: number, tasks_updated: number }`.
  - Add `api.resyncVault: () => Promise<VaultSyncResult>`.

- [ ] **Step 3: Update `frontend/src/components/SettingsView.tsx`**
  - In the Obsidian Vault Card:
    - Add live status badge:
      - 🟢 `Watching Vault (${settings.vault_dir})` when `vault_sync` is true.
      - ⚪ `Sync Disabled` when false.
    - Add "Force Vault Re-sync" button with loading state.
    - On click, call `api.resyncVault()` and show toast (`Re-synced X notes, imported Y notes, updated Z tasks`).

- [ ] **Step 4: Run tests and build**
  - Run: `cd frontend && npm test`
  - Run: `cd frontend && npm run build`

- [ ] **Step 5: Commit**
  - `git add frontend/src/types.ts frontend/src/api.ts frontend/src/components/SettingsView.tsx frontend/src/components/__tests__/SettingsView.test.tsx`
  - `git commit -m "feat(ui): add vault watching status indicator and force re-sync action to settings"`
