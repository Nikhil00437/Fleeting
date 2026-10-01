# Fleeting Visual Overhaul & Interactive Data-Studio Design

**Date:** 2026-09-30
**Status:** Approved for Spec Review

## 1. Overview & Goals

Transform Fleeting's frontend from a basic status viewer into a **Vibrant Data-Studio Interactive Desktop App** while keeping zero external chart library dependencies and 100% local-first execution:

1. **Vibrant Data-Studio Aesthetic:** Rich multi-layered glassmorphic surfaces, bolder ember/iris/cyan/emerald gradients, glowing status indicators, and responsive card-grid layouts.
2. **Full Interactive Graph & Visualization Suite:** Click-to-filter charts (`Bars`, `AreaTrend`, `Donut`, `StackBar`), a new 24-hour horizontal `SessionRibbon` (Gantt-style activity timeline), multi-range selectors (`7D`, `14D`, `30D`), average reference lines, peak badges, and floating glass tooltips.
3. **Interactive App Workflows Across All Views:**
   - **Timeline:** Cross-filtering by app and hour across all charts, window title breakdowns, and the session feed; interactive date jumping from multi-day trend charts; expandable project file/commit cards.
   - **Inbox:** Hero telemetry dashboard (capture trend with `7D`/`14D`/`30D` toggle, capture type split bar, task completion ring), interactive filter bar (`All`, `Text`, `Voice`, `YouTube`, tag filter, search filter), layout switcher (`Grid` vs. `List`), and inline action-item completion directly on note cards.
   - **Tasks:** Interactive status tabs (`Open`, `Done`, `All`), grouping mode (`By Note` vs. `Chronological`), text filter, and visual completion telemetry.
   - **Search:** Proportional tag frequency bars, type filters (`All`, `Text`, `Voice`, `YouTube`), and instant tag/query filtering.
4. **Sorted & Compartmentalized Settings View:** Replace the single long scroll with a **Live System Health Banner** at the top and **5 Segmented Sub-Tabs** (`AI & Speech`, `Activity & Privacy`, `App Rules`, `Vault & Ingestion`, `System Diagnostics`).

---

## 2. Backend Telemetry Extensions

To power multi-range capture trends, capture type breakdowns, and task/system views without breaking any existing API contracts:

- **`GET /api/stats?days=7`** ([backend/fleeting/routers/search.py](file:///home/nikhil/Projects/fleeting/backend/fleeting/routers/search.py), [backend/fleeting/db.py](file:///home/nikhil/Projects/fleeting/backend/fleeting/db.py)):
  - Fix `Database.notes_per_day(days: int = 7)` so it queries the requested `days` window (`2..60`) instead of a hardcoded 6-day window.
  - Accept `days: int = 7` query parameter on `GET /api/stats`.
  - Include `by_type: { text: int, voice: int, youtube: int }` in `Database.stats()` so the Inbox and Search views can render accurate capture-type distributions across all notes.
- **`GET /api/tasks?include_done=false`** ([backend/fleeting/routers/search.py](file:///home/nikhil/Projects/fleeting/backend/fleeting/routers/search.py), [backend/fleeting/db.py](file:///home/nikhil/Projects/fleeting/backend/fleeting/db.py)):
  - Allow optional `include_done: bool = False` query parameter on `/api/tasks` (default `False` preserves existing behavior and tests) where each returned item includes `done: bool`, enabling the Tasks view to filter between `Open`, `Completed`, and `All` tasks.
- **`GET /api/health`** ([frontend/src/api.ts](file:///home/nikhil/Projects/fleeting/frontend/src/api.ts)):
  - Expose `api.health()` on the frontend client to power the Settings live status banner and System Diagnostics tab.

---

## 3. Component Architecture

### 3.1 Styling & Theme ([frontend/src/index.css](file:///home/nikhil/Projects/fleeting/frontend/src/index.css))
- Add vibrant accent tokens (`cyan`, `emerald`, `rose`) alongside `ember` and `iris`.
- Add `.glass-studio`, `.glass-interactive`, `.neon-pill`, and subtle grid-pattern backdrop utilities.
- Smooth transitions for chart selections, tab switches, and card grid reflows.

### 3.2 Interactive Chart Kit ([frontend/src/components/charts.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/charts.tsx))
- **`Bars`:**
  - Props: `data: { key?: string; label: string; value: number; sub?: string; hint?: string; color?: string }[]`, `selectedIndex?: number | null`, `onSelect?: (index: number) => void`, `showAvg?: boolean`, `color`, `secondaryColor`, `height`, `format`.
  - Features: Clickable bars with active glow ring, dashed horizontal average line, floating glass tooltip with primary + secondary readout, and smooth grow animation.
- **`AreaTrend`:**
  - Smooth SVG cubic-bezier or polyline area chart with gradient fill, data point nodes, hover scrubber tooltip, and click-to-select point support.
- **`Donut`:**
  - Interactive SVG ring segments with hover/click selection (`selectedKey`, `onSelect`), dynamic center label that updates on hover/selection to show the active slice's value & percentage, and drop-shadow glow on the active arc.
- **`StackBar`:**
  - Horizontal proportional bar with clickable segments (`selectedKey`, `onSelect`), hover scale/glow, and optional legend pills.
- **`SessionRibbon` (24h Gantt Strip):**
  - Plots `ActivitySession[]` across a 00:00–24:00 horizontal axis using `first_seen`, `last_seen`, and `appColor(app_class)`.
  - Supports clicking a session block to filter by its `app_class` and hovering to inspect exact timestamps, window title, and active duration.

### 3.3 App Shell & Capture Bar ([frontend/src/App.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/App.tsx), [frontend/src/components/CaptureBar.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/CaptureBar.tsx))
- **Sidebar Studio Rail:**
  - Upgraded brand header, navigation items with live counts and shortcut kbd badges, and an interactive **Live Telemetry Card** (clicking the live window or sparkline opens Timeline; clicking open tasks opens Tasks).
- **Capture Bar:**
  - Auto-detects input mode (`Thought` vs. `YouTube Link` vs. `Task`) with a live mode badge, quick-submit button in addition to `Enter`, and an upgraded multi-bar audio visualizer with elapsed timer and cancel/send controls during voice recording.

### 3.4 Timeline Studio ([frontend/src/components/TimelineView.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/TimelineView.tsx))
- **Top Control Bar:** Date navigator (`Prev`, `Date Picker / Today`, `Next`), active filter pills (`App: <app> ✕`, `Hour: <HH:00> ✕`), KPI summary badges (Total Tracked, Sessions, Active Apps, Peak Hour), and Live Pause/Resume switch.
- **Hero Visual Grid:**
  - **Multi-Day Activity Trend (`7D` / `14D` / `30D`):** Switchable between `Bars` and `AreaTrend`, showing average line and total hours; clicking any day bar navigates the Timeline to that day.
  - **Interactive App Time Split (`Donut` + `StackBar` + Interactive Legend):** Clicking any app slice or legend row toggles `selectedApp` cross-filtering across the entire view, and reveals the top window titles for that app.
- **24-Hour Activity Rhythm & Session Ribbon:**
  - Combines the **24h `SessionRibbon` Gantt strip** with the **Hourly Activity `Bars` chart**. Clicking an hour bar toggles `selectedHour` filtering on the session feed.
- **Daily AI Report & Workspace Activity:**
  - Styled AI report card with model badge, copy-markdown button, and regenerate button.
  - Interactive **Files & Git Commits** compartment with expandable file groups, extension distribution pills, and git commit subjects per repository.
- **Filterable Session Feed:**
  - Searchable, filterable by `selectedApp` and `selectedHour`, with proportional duration bars per row.

### 3.5 Inbox, NoteCard, Tasks & Search ([frontend/src/components/Inbox.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/Inbox.tsx), [frontend/src/components/NoteCard.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/NoteCard.tsx), [frontend/src/components/TasksView.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/TasksView.tsx), [frontend/src/components/SearchView.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/SearchView.tsx))
- **Inbox:**
  - **Data-Studio Hero Strip:** KPI counters (`Today`, `7d/14d/30d`, `Total`), selectable `7D`/`14D`/`30D` capture trend chart, Capture Type Split (`Text` / `Voice` / `YouTube` proportional bar + counts), and Task Completion Ring.
  - **Interactive Toolbar:** Type filter pills (`All`, `Text`, `Voice`, `YouTube`), active tag filter pill, sort order (`Newest`, `Oldest`), and layout toggle (`Grid` 2-col vs. `List` 1-col).
  - **Enhanced `NoteCard`:** Distinct color-coded type badges, clickable tags (clicking a tag filters Inbox by that tag), inline action-item preview with interactive checkboxes, and quick pin/open actions.
- **TasksView:**
  - Hero completion card with `Ring`, completion bar, and KPI counters.
  - Filter controls: `Open` / `Completed` / `All` segmented control, grouping toggle (`By Note` vs. `All Tasks`), and instant text filter.
- **SearchView:**
  - Instant search bar with type filter pills (`All`, `Text`, `Voice`, `YouTube`).
  - Interactive **Tag Analytics Grid** (when query is empty or alongside results) showing proportional frequency bars for top tags; clicking any tag runs a tag search.

### 3.6 Compartmentalized Settings View ([frontend/src/components/SettingsView.tsx](file:///home/nikhil/Projects/fleeting/frontend/src/components/SettingsView.tsx))
- **Live System Health Banner:** Displays real-time status indicators for **SQLite FTS5 DB**, **LLM Provider**, **Whisper STT**, **Hyprland Collector**, and **Markdown Vault**.
- **5 Segmented Compartments:**
  1. **AI & Speech:**
     - *Local LLM Card:* Visual provider selector (`Ollama`, `LM Studio`, `Offline Heuristics`), model input + clickable discovered model pills from "Test Connection", Base URL, and timeout control.
     - *Whisper STT Card:* Visual 4-tier model cards (`tiny`, `base`, `small`, `medium`) showing speed/accuracy trade-offs, language setting, and live model loader/tester.
  2. **Activity & Privacy:**
     - Collector master toggle, midnight auto-daily-report toggle, poll interval & idle threshold controls, interactive chip list for `excluded_apps`, and interactive chip list for `watch_dirs`.
  3. **App Rules (`Trace Apps Individually`):**
     - Summary metrics (Total Apps, Traced, Muted), search input, status filter (`All`, `Traced`, `Muted`), bulk actions, and sorted app list with color badges, time-spent bars, session counts, and per-app tracking toggles.
  4. **Vault & Ingestion:**
     - Markdown Vault directory configuration, writability status badge, auto-sync note toggle, daily-report vault mirror toggle, YouTube audio fallback toggle + max duration control, and desktop notifications switch.
  5. **System Diagnostics:**
     - Live `/api/health` telemetry (version, uptime, queue depth, whisper state), config path display with copy button, and manual refresh/test triggers.

---

## 4. Error Handling & Testing

- **Graceful Degradation:** All charts handle empty datasets (`0` sessions, `0` notes) with clean studio empty states; offline LLM or unreachable Whisper states surface clear non-blocking badges.
- **Testing:**
  - Backend pytest suite (`uv run pytest`) updated to test `GET /api/stats?days=14`, `by_type` counts, and `GET /api/tasks?include_done=true`.
  - Frontend TypeScript + Vite production build (`bun run build` / `npm run build`) verified with zero type or bundle errors.
