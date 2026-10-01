# Fleeting Visual Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a full Vibrant Data-Studio visual and interactive overhaul across Fleeting's charts, views (Timeline, Inbox, Tasks, Search), App Shell, and a 5-compartment Settings View with a live system health banner.

**Architecture:** Zero-dependency SVG/CSS interactive chart suite (`Bars`, `AreaTrend`, `Donut`, `Ring`, `Spark`, `StackBar`, `SessionRibbon`) coupled with cross-filtering React state across views, a 5-tab compartmentalized `SettingsView` powered by live `/api/health` + `/api/settings` endpoints, and targeted backend extensions on `/api/stats` and `/api/tasks`.

**Tech Stack:** Python 3.13, FastAPI, SQLite, React 19, TypeScript 5.8, Tailwind CSS 4, Vite 7.

**Spec:** `docs/superpowers/specs/2026-09-30-visual-overhaul-design.md`

## Global Constraints

- Zero external chart library dependencies (keep bundle fast and self-contained).
- 100% local-first execution; preserve all existing keyboard shortcuts (`n`, `/`, `t`, `a`, `Escape`) and SSE real-time updates.
- Backward-compatible API changes so all existing pytest tests continue to pass alongside new tests.

---

### Task 1: Backend Telemetry Extensions (`/api/stats` & `/api/tasks`)

**Files:**
- Modify: `backend/fleeting/db.py:348-364`, `backend/fleeting/db.py:440-489`
- Modify: `backend/fleeting/routers/search.py:26-38`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces:
  - `GET /api/stats?days=7` -> `{ total, today, week, open_tasks, done_tasks, queue, by_type: { text, voice, youtube }, notes_per_day: [{ day, count }] }`
  - `GET /api/tasks?include_done=false` -> `[{ note_id, note_title, item_id, text, done, created_at }]`

- [ ] **Step 1: Write failing tests in `backend/tests/test_api.py`**
- [ ] **Step 2: Run `uv run pytest` to verify failure**
- [ ] **Step 3: Implement `notes_per_day(days)`, `stats()` with `by_type`, and `open_tasks(include_done=...)` in `backend/fleeting/db.py` and `backend/fleeting/routers/search.py`**
- [ ] **Step 4: Run `uv run pytest` to verify all backend tests pass**

---

### Task 2: Design System, Types, API Client & Icons

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/components/Icons.tsx`

**Interfaces:**
- Produces:
  - Updated `Stats`, `TaskRef`, `HealthStatus` types in `frontend/src/types.ts`
  - `api.stats(days?: number)`, `api.tasks(includeDone?: boolean)`, `api.health()` in `frontend/src/api.ts`
  - Studio CSS utilities (`.glass-studio`, `.glass-interactive`, `.studio-grid-bg`, `.badge-glow`, vibrant theme tokens) in `frontend/src/index.css`
  - Additional icons (`GridIcon`, `ListIcon`, `FilterIcon`, `CpuIcon`, `DatabaseIcon`, `ShieldIcon`, `SlidersIcon`, `FolderIcon`, `TerminalIcon`, `SendIcon`, `BoltIcon`, `EyeIcon`) in `frontend/src/components/Icons.tsx`

- [ ] **Step 1: Update `frontend/src/types.ts` and `frontend/src/api.ts`**
- [ ] **Step 2: Expand `frontend/src/components/Icons.tsx` and `frontend/src/index.css`**

---

### Task 3: Interactive Chart & Graph Suite (`charts.tsx`)

**Files:**
- Modify: `frontend/src/components/charts.tsx`

**Interfaces:**
- Produces:
  - `Bars`: Interactive bar chart with `selectedIndex`, `onSelect`, `showAvg`, peak highlight, custom per-bar colors, and floating glass tooltip.
  - `AreaTrend`: Smooth SVG area/line chart with interactive hover/click points, gradient fill, average line, and floating tooltip.
  - `Donut`: Multi-segment interactive SVG donut with `selectedKey`, `onSelect`, hover state, and dynamic center readout.
  - `Ring`: Animated circular gauge with glow filter.
  - `Spark`: Interactive mini area sparkline.
  - `StackBar`: Interactive proportional horizontal bar with clickable segments (`selectedKey`, `onSelect`).
  - `SessionRibbon`: 24-hour horizontal Gantt timeline strip plotting `ActivitySession[]` across `00:00`–`24:00` with hover inspection and click-to-filter by app.

- [ ] **Step 1: Implement upgraded interactive components in `frontend/src/components/charts.tsx`**

---

### Task 4: Timeline Studio View (`TimelineView.tsx`)

**Files:**
- Modify: `frontend/src/components/TimelineView.tsx`

**Interfaces:**
- Consumes: `Bars`, `AreaTrend`, `Donut`, `StackBar`, `SessionRibbon` from `./charts`
- Produces: Full interactive Timeline Studio with:
  - `7D` / `14D` / `30D` range selector and `Bar` / `Area` chart mode toggle
  - Click-any-day bar to jump to that date
  - Cross-filtering by `selectedApp` (via Donut, StackBar, SessionRibbon, or Legend) and `selectedHour` (via Hourly Bars)
  - 24h `SessionRibbon` Gantt timeline + Hourly Rhythm chart
  - Top Window Titles breakdown card for the active day/app
  - Expandable Files & Git Activity cards and searchable/filterable Session Feed with duration bars

- [ ] **Step 1: Implement overhauled `frontend/src/components/TimelineView.tsx`**

---

### Task 5: Inbox, NoteCard, TasksView, SearchView & App Shell Overhaul

**Files:**
- Modify: `frontend/src/components/NoteCard.tsx`
- Modify: `frontend/src/components/Inbox.tsx`
- Modify: `frontend/src/components/TasksView.tsx`
- Modify: `frontend/src/components/SearchView.tsx`
- Modify: `frontend/src/components/CaptureBar.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces:
  - `NoteCard`: Type-colored accents, inline interactive action-item checkboxes, clickable tag pills (`onTagClick`), and compact/card variants.
  - `Inbox`: Hero Data-Studio telemetry strip (`7D`/`14D`/`30D` trend chart, Capture Type split bar + legend, Task Completion ring), interactive filter bar (Type pills, active Tag pill, text filter, Grid/List view toggle), and inline task toggling.
  - `TasksView`: Interactive status tabs (`Open`, `Completed`, `All`), grouping mode (`By Note` vs. `Chronological`), search filter, and completion telemetry header.
  - `SearchView`: Type filter pills, interactive Tag Analytics distribution chart with proportional bars, and highlighted FTS5 results.
  - `CaptureBar` & `App`: Live mode badge, quick-send button, multi-band audio visualizer, upgraded sidebar navigation & interactive Today telemetry card, plus `s` shortcut for Settings.

- [ ] **Step 1: Update `NoteCard.tsx` and `Inbox.tsx`**
- [ ] **Step 2: Update `TasksView.tsx` and `SearchView.tsx`**
- [ ] **Step 3: Update `CaptureBar.tsx` and `App.tsx`**

---

### Task 6: Sorted & Compartmentalized Settings View (`SettingsView.tsx`)

**Files:**
- Modify: `frontend/src/components/SettingsView.tsx`

**Interfaces:**
- Consumes: `api.settings()`, `api.updateSettings()`, `api.knownApps()`, `api.setAppTracked()`, `api.testLLM()`, `api.testWhisper()`, `api.health()`
- Produces:
  - **Live System Health Banner** (DB, Local LLM, Whisper STT, Hyprland Collector, Markdown Vault)
  - **5 Segmented Compartments:**
    1. `AI & Speech` (Provider selector cards, clickable discovered model chips, Whisper 4-tier visual model cards, live testers)
    2. `Activity & Privacy` (Collector master switches, poll/idle controls, interactive tag/chip editors for Excluded Apps and Watch Dirs)
    3. `App Rules` (Searchable, filterable `All`/`Traced`/`Muted` table with usage bars, session counts, bulk enable/mute, and individual toggles)
    4. `Vault & Ingestion` (Obsidian vault path + writability status, sync toggles, YouTube fallback & duration slider, desktop notifications)
    5. `System Diagnostics` (Live `/api/health` metrics, uptime, queue status, config path copy)

- [ ] **Step 1: Implement compartmentalized `frontend/src/components/SettingsView.tsx`**
- [ ] **Step 2: Run `bun run build` in `frontend/` and `uv run pytest` in `backend/` to verify zero errors**
