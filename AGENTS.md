# AGENTS.md

Local-first capture & memory inbox: FastAPI + SQLite(WAL/FTS5) backend, React 19 +
Vite SPA, Electron shell (tray + dictation HUD), Hyprland activity tracker. No cloud,
no API keys required — every LLM/embedding call has a local heuristic fallback.

## Commands

```bash
./scripts/install.sh              # uv sync (backend) + bun install && bun run build (frontend)
./scripts/dev-restart.sh          # kill + restart uvicorn on 127.0.0.1:7425, waits for /api/health
./scripts/install-app.sh          # launcher entry + icon + `flee` on PATH
bin/fleeting-app                  # Electron shell (probes :7425, spawns backend itself)
bin/fleeting-app --hud            # dictation HUD window only (?mode=hud)
bin/fleeting-app --capture        # focus the capture bar — only honoured on a *second*
                                 # instance (second-instance → app:navigate); a cold
                                 # start ignores it, only --hud is checked there
flee "some thought"               # POST to the running API from a Hyprland keybind

cd backend && uv run pytest                          # 507 tests, ~15s
cd backend && uv run pytest tests/test_tasks_db.py            # single file
cd backend && uv run pytest tests/test_tasks_db.py -k task_crud   # single test by name
cd frontend && bun run test                          # 214 vitest tests, ~1.3s (node env)
cd frontend && bun run build                         # tsc -b && vite build -> frontend/dist
cd frontend && bun run dev                           # vite :5173, proxies /api -> :7425
```

`backend/dist` is **not** where the SPA lives — the backend serves `frontend/dist`
directly (`_mount_frontend`). Rebuild the frontend or the served app is stale.

## Layout & wiring

- `backend/fleeting/main.py` — `create_app()` factory. `app = create_app()` at module
  level means importing the module touches the real DB. Tests must use
  `create_app(cfg, load_from_disk=False)`.
- Routers get `app.state.st` (`state.py`) for `cfg`/`db`/`bus`/`processor`.
  There is no DI container — reach for `request.app.state.st`.
- `services/` holds domain logic; `routers/` stays thin (validate → service → publish
  an SSE event).
- **Every write that the UI must see live must `bus.publish(...)`.** Event names are
  load-bearing on the frontend: `note.created|updated|deleted`, `task.*`,
  `activity.live`, `dailylog.updated`, `whisper.progress`. Miss one and the view goes
  stale until navigation. Adding a call site without a reducer branch in
  `frontend/src/components/serverEvents.ts` is the usual bug.
- `services/process.py` — capture pipeline. Captures insert as `status=pending`, API
  returns immediately, `Processor` (2 workers, queue cap 500) drains it. Blocking work
  (whisper/ffmpeg/yt-dlp) runs in threads.
- `activity.py` — Hyprland poll loop → sessions. The state machine (`poll_once`) is
  separate from the probes specifically so tests can drive it without Hyprland.
- `electron/main.cjs` — tray, HUD window, backend supervision, clipboard/`wtype`
  injection. Preload exposes `window.fleetingDesktop`; the SPA feature-detects it.

## Database

- Migrations are **append-only strings in `MIGRATIONS`** (`db.py`), applied by
  `migrate()` with `BEGIN/COMMIT` wrapping. Never edit an applied migration. Never
  put data migration in `Database.__init__` (it runs per request-thread).
- `Database` is thread-local (`check_same_thread=False` + WAL). Call `commit()`
  explicitly — there is no ORM and no unit of work.
- `update_note()` silently drops any key not in `NOTE_COLUMNS`. Adding a notes column
  means adding it there too, or PATCHes will appear to succeed and do nothing.
- FTS tables are external-content and **map columns by name**; new indexed columns
  need a new migration version. Triggers (`notes_ai/ad/au`, `activity_*`) keep them in
  sync. Rebuild with `INSERT INTO <fts>(<fts>) VALUES('rebuild')` — a plain
  `INSERT…SELECT` leaves rows that `MATCH` never returns.
- `notes.type` is the column; `note_type` is only the Python kwarg name in
  `list_notes()`. `insert_note({"note_type": …})` is silently ignored — pass `type`.

## Security invariants (three layers, all tested in `test_auth.py` / `test_csrf.py`)

1. **Host allow-list** (`guard_api`) — rejects rebinding; foreign `Host` → 421.
2. **Bearer token** on mutating `/api` routes when `activity.api_token` is set.
   `/api/health` is exempt. `secrets.compare_digest`, never `==`.
3. **Origin check** (`guard_cross_origin_writes`) — CORS stops *reading* a response,
   not *sending* a simple POST. Missing `Origin` = non-browser client (curl, `flee`)
   and is allowed; literal `null` is rejected.

New mutating endpoints inherit all three automatically — do not add a route outside
`/api` expecting protection. `TestClient` in tests must use a real `base_url`
(`http://127.0.0.1:<port>`) or the Host guard rejects it; the `client` fixture in
`conftest.py` already does.

`[llm].api_key` is plaintext in `~/.config/fleeting/config.toml` by design. The
settings API never returns it, only whether one is set.

## Config

`~/.config/fleeting/config.toml`, mutable by hand **and** via Settings. So:
- `save_config()` is atomic (tmp + `os.replace`) and **comment/unknown-key preserving**
  — don't "simplify" it into `toml.dump`.
- `load_config()` degrades per value; an unreadable file is never overwritten.
- Add a setting as a dataclass field in one of the `_SECTIONS` classes; serialization
  is derived from `fields()`, no registration step.
- Tests monkeypatch `fcfg.DB_PATH` / `fcfg.CONFIG_PATH` — but `_db_path()` reads
  `DB_PATH` from the module at call time, so patch the module attribute, not a
  local.

## Tests

- Backend: pytest, `testpaths=["tests"]`, no network (fixtures force
  `llm.provider="none"` and `activity.enabled=False`). Use the `client` fixture for
  API tests; `wait_done(client, note_id)` polls the async pipeline instead of sleeping.
- Frontend: vitest defaults to **`environment: "node"`** for speed — most tests assert
  `renderToStaticMarkup`. Tests that need effects/events/error boundaries must be named
  `*.dom.test.tsx` **and** carry a `@vitest-environment jsdom` docblock. A behaviour
  test without the docblock silently renders but never runs its effects.
- Pure logic belongs in a module, not in a component: `serverEvents.ts`, `weekly.ts`,
  `backfill.ts`, `unifiedSearch.ts`, `processOwnership.ts` exist because logic inside
  `useEffect` is untestable with the SSR-string renderer. Follow that pattern.

## Conventions

- Conventional commits, one logical change each: `feat(inbox):`, `fix(processes):`,
  `chore:`, `refactor(ui):`, `docs:`. History is on `main` with direct pushes.
- Python 3.12+, `from __future__ import annotations`, full type hints on new code.
  Comments explain *why* (see `db.py` migrate/insert-note history) — the codebase
  documents its own past bugs; keep that habit.
- **No linters or formatters are configured** (no ruff/eslint/pre-commit). `tsc -b`
  is the only frontend gate (`noUnusedLocals`, `noUnusedParameters`, `strict` all on).
  Match surrounding style; don't introduce a new toolchain in a feature PR.
- Tailwind 4 via the Vite plugin, no config file. Design tokens are CSS custom
  properties in `index.css` (`--ink-*`, `--ember-*`) plus shared classes
  (`glass-studio`, `app-toolbar`, `micro-label`, `badge-p1`) — extend those, don't
  invent a parallel scale.
- Accessibility is tested, not assumed: `components/a11y.ts` + `*.test.ts` files check
  it. New interactive elements need labels and keyboard paths.
- Frontend state is local `useState` + `refreshKey` counters; there is no client store.
  SSE arrives through `applyServerEvent` in `App.tsx`.

## Planning

`future_ideas.md` holds 500 raw ideas. `docs/versions/` re-cuts them into shippable
releases — one file per version with the data model it needs. Read
`docs/versions/README.md` before planning new work. Historical plans/specs live in
`docs/superpowers/{plans,specs}/`; execution artefacts in `.superpowers/sdd/`.

## Gotchas

- `README.md` test counts and the "Ideas for v2" section are stale (it still lists
  the weekly digest and embeddings as future work — both shipped).
- Activity rows are pruned on boot to `activity.retention_days` (default 30).
  Daily reports only ever look back 24h; a shorter window breaks nothing.
- Embedding dimensionality follows the LLM model. Switching models invalidates the
  whole vector corpus, so `create_app` schedules a backfill on boot — check
  `test_embedding_migration.py` before touching that path.
- `Processor.WORKERS = 2` is a deliberate ceiling (a YouTube + whisper capture can
  chain ~22 min of subprocess work behind one worker).
- `System` runs on a timer/date boundary, not cron: daily report at midnight, weekly
  on Monday boot, hourly milestone digests off accumulated active screentime.
