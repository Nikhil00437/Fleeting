# ⚡ Fleeting

**A local-first memory inbox for your computer.** Voice memos, stray thoughts and
YouTube links go in — clean, titled, tagged, searchable notes come out. Meanwhile
Fleeting quietly watches which windows you work in and writes you a **daily log**
with your local LLM. Everything runs on your machine: no cloud, no API keys, no
telemetry.

> "If the cloud goes down, my tools should still work." — this one does.

```
┌────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
│  capture   │ → │  transcribe  │ → │   organize    │ → │  file & sync │
│ text/mic/  │   │  faster-     │   │ local LLM via │   │ SQLite FTS5  │
│ youtube    │   │  whisper     │   │  Ollama       │   │ markdown vault│
└────────────┘   └──────────────┘   └───────────────┘   └──────────────┘

┌────────────┐   ┌──────────────────────────────────────────────┐
│  observe   │ → │  daily log: compact sessions → LLM summary   │
│ hyprctl    │   │ mirrored to <vault>/Daily/YYYY-MM-DD.md      │
└────────────┘   └──────────────────────────────────────────────┘
```

![Fleeting workspace](assets/demo.gif)

Seeded demo data, captured from the real app — the middle of the loop is a
capture made somewhere else landing in the inbox without a reload.

## What it does

- **Capture anything, instantly** — type in the always-present bar, hit the mic
  for a voice memo (recorded in the browser), or paste a YouTube URL. Processing
  happens in the background with live SSE updates in the UI.
- **Voice memos → text** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
  (CPU, int8) transcribes fully offline. Model size: tiny → medium.
- **YouTube → notes** — [yt-dlp](https://github.com/yt-dlp/yt-dlp) pulls metadata
  and captions; caption-less videos fall back to local audio transcription
  (opt-in, duration-capped).
- **Local LLM organizes everything** — your Ollama (or LM Studio) model turns raw
  captures into a title, a summary, tags and concrete action items. If the LLM is
  down, a built-in heuristic pass keeps the app fully functional.
- **Tasks surface automatically** — every "remember to…" becomes a checkbox in
  the Tasks view, linked back to its note.
- **Timeline — your day, logged** — a background collector (Hyprland `hyprctl`)
  tracks the active window, merges it into compact sessions with real active
  seconds (idle detection via cursor stillness), and shows a live "on your
  screen now" card, a per-app time-split bar and a chronological session feed.
- **It knows what you saved, not just where you were** — the daily report also
  scans your watch dirs (`~/Projects`, `~/Documents`, `~/Downloads`) for files
  modified in the window and pulls git commit subjects — metadata only, never
  file contents. The report can therefore say *what* you built, not just which
  app was open.
- **Daily report at 12:00 AM, past 24 hours, inside the app** — every midnight
  the local model compacts the past 24 hours (window sessions + save-file
  activity + commits) into a readable markdown report — overview, time split,
  what happened, threads & loose ends — delivered in the app (with a toast when
  it lands). If the laptop was off at midnight, it's written on next startup.
  Falls back to a deterministic digest when the model is unreachable. Reports
  live in the app; an optional settings toggle also mirrors them to the vault.
- **Per-app tracing switches** — Settings lists every app the tracker has seen
  with an individual on/off toggle; a blocklist (zen browser by default) keeps
  chosen apps out entirely.
- **Everything is searchable** — SQLite FTS5 over titles, transcripts and tags
  with highlighted snippets, optionally reranked against note embeddings.
- **Process view** — active windows and a sortable process list with CPU and
  memory, per-process runtime details, and terminate. Hyprland is the supported
  compositor; Sway and X11/wmctrl are attempted as fallbacks.
- **Your data stays yours** — one SQLite file plus plain Markdown in your vault.
  Pause tracking any time from the Timeline view; exclude apps by name in
  settings. Nothing ever leaves the machine.

## It's a desktop app

The real shell is **Electron** (`electron/main.cjs`, launched by `bin/fleeting-app`).
It gives you:

- **Auto-backend** — probes `127.0.0.1:7425` and starts the FastAPI server itself
  if nothing answers, so there is no second thing to launch.
- **System tray icon** with a tooltip, plus window position/size persistence.
- **A dictation HUD** — a separate always-on-top, all-workspaces window
  (`?mode=hud`) toggled by <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd>, so the
  mic is always one keypress away without covering your work.

`scripts/install-app.sh` installs a launcher entry ("Fleeting" in wofi/rofi)
with an icon that runs `fleeting-app`, which locates your `electron` binary.

> Window note: the shell sets `StartupWMClass=fleeting`, so Hyprland rules match
> on `class:^(fleeting)$` — for example
> `windowrulev2 = pin, class:^(fleeting)$`.

## Stack

| Layer     | Tech                                                        |
| --------- | ----------------------------------------------------------- |
| Backend   | Python 3.13, FastAPI, SQLite (WAL + FTS5), asyncio workers   |
| AI        | faster-whisper (local STT), Ollama / LM Studio (local LLM)  |
| Ingestion | yt-dlp, ffmpeg, hyprctl (activity), psutil (process view)   |
| Frontend  | React 19, Vite 7, Tailwind 4, TypeScript                    |
| Realtime  | Server-Sent Events                                          |
| Shell     | Electron (tray, HUD, auto-backend), systemd user service     |

## Setup (Arch / Omarchy)

```bash
cd ~/Projects/fleeting
./scripts/install.sh          # uv sync + bun/npm build
./scripts/install-app.sh      # launcher entry, icon, `flee` on PATH
./scripts/dev-restart.sh      # start the server
```

Open the **Fleeting** entry in your launcher (or http://127.0.0.1:7425).
First boot auto-detects your Ollama model and creates
`~/.config/fleeting/config.toml`.

Requirements: `uv`, `bun` (or npm), `ffmpeg`, `yt-dlp`, and Hyprland's
`hyprctl` for activity tracking. `electron` (or `electron43`) is needed for the
desktop shell. The whisper model downloads once on first
voice capture (`base` is ~75 MB and usually already in your HuggingFace cache).

### Run as a service (survives reboots)

```bash
cp deploy/fleeting.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now fleeting
```

### Quick capture from anywhere

```bash
flee "ship the portfolio site"              # capture a thought
echo "check the invoice" | flee             # from a pipe
flee --youtube https://youtu.be/aircAruvnKk # send a video
```

### Experimental endpoints

Three things shipped before anything was built to reach them. They are **off** by
default; turn one on in `~/.config/fleeting/config.toml`:

```toml
[experimental]
tone = true            # GET  /api/notes/tone          urgency/sentiment ordering
benchmark = true       # POST /api/benchmark/run      score models on your own notes
pinned_context = true  # notes pinned into an assistant thread
sql_console = true      # POST /api/sql                 read-only SELECT over the schema
```

`GET /api/health` reports which are on. They are gated with a **404** rather than
a 403, so an off flag looks exactly like a route that was never written.

## Configuration

`~/.config/fleeting/config.toml` (also editable in the Settings UI):

```toml
[paths]
vault_dir = "~/Documents/FleetingVault"   # markdown mirror
vault_sync = true

[llm]
provider = "ollama"            # ollama | lmstudio | custom | none
base_url = "http://127.0.0.1:11434"
model = ""                     # empty = auto-detect first chat-capable model
api_key = ""                   # optional bearer token for custom/OpenAI-compatible

[transcribe]
model = "base"                 # tiny | base | small | medium
language = "auto"

[youtube]
transcribe_fallback = true     # whisper videos without captions
max_duration_min = 45

[activity]
enabled = true                 # requires restart when toggled
poll_secs = 20
idle_after_min = 3             # cursor-still minutes = away
excluded_apps = "zen"          # never traced, regardless of per-app toggles
auto_daily_log = true          # past-24h report at 12:00 AM
watch_dirs = "~/Projects, ~/Documents, ~/Downloads"
mirror_daily_log = false       # reports live in the app; flip to also mirror

[notifications]
desktop = true
```

Data lives in `~/.local/share/fleeting/` (`fleeting.db` + audio). The server
binds to `127.0.0.1` only — it is a single-user local app.

If you set an `api_key` it is stored **in plaintext** in
`~/.config/fleeting/config.toml`; keep that file readable only by you. The
Settings API never returns the stored key, only whether one is set.

Because a browser will happily fire a cross-origin `POST` at a loopback port
without any user intent, every mutating `/api` request must carry an `Origin`
header belonging to the app itself (or the Vite dev server). Requests with no
`Origin` — `curl`, the `flee` CLI, scripts — are unaffected. A future browser
extension will therefore need to declare itself allowed here rather than assume
it can post freely.

For how a capture actually travels through the app — and the invariants that
are not visible from reading any single file — see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Layout

```
backend/
  fleeting/
    main.py            app factory, SPA + app-window serving, lifespan
    config.py          TOML config, XDG paths
    db.py              SQLite + FTS5 + migrations (notes, activity, daily_logs, kv)
    process.py         capture pipeline (transcribe → enrich → sync)
    activity.py        Hyprland window tracker (idle-aware session state machine)
    events.py          SSE event bus
    services/          llm, transcribe, youtube, markdown, dailylog
    routers/           notes, capture, search, settings, system, activity, processes
  tests/               pytest (API E2E, collector, daily log, markdown, subtitles)
frontend/              React 19 + Tailwind 4 SPA (Inbox, Timeline, Tasks, Search, Settings)
electron/              desktop shell: tray, HUD window, backend supervision
scripts/               install.sh, install-app.sh, dev-restart.sh
deploy/                systemd user unit, .desktop entry, app icon
bin/                   flee (CLI capture), fleeting-app (desktop launcher)
```

## Plugins

A folder in `~/.config/fleeting/plugins/` with a `plugin.json` declaring capture
sources, enrichers and views. `GET /api/plugins` lists them and reports what is
wrong with the ones that will not load.

The manifest is a **catalogue, not an execution vector**. Running things is
[hooks](#hooks) and `actions.toml`, which are opt-in per file; a manifest only
*names* a hook, and that hook still has to be installed by you. The loader copies
only keys it knows, so a `"command"` or `"script"` field in a manifest is dropped
without being read — a plugin folder someone sent you is data, not code.

See `plugins/README.md` for the format and `plugins/notion-sync/` for a worked
example.

## What it stores

`GET /api/inventory`, and Settings → **System** under Storage. Every category
with its size, largest first — notes, tasks, activity, the database file, audio,
attachments, the vault export and the log.

Bytes come from the filesystem, not from summing column lengths: a blob, an
audio file and a row of text are not comparable, and `length()` under-reports by
the page overhead SQLite actually spends. The database is `page_count *
page_size`, which is the number disk-usage tools show.

`deletable` is on every row, because that is the field that stops it
misreporting: notes come from a capture, and the database file does not shrink
because you deleted a note. Trashed notes are counted separately — they are
still on disk.

## What leaves your machine

Settings → **System → Diagnostics** shows it, and `GET /api/offline` returns it.

The answer for a default install is **not zero**, and the page says so:

| Feature | Leaves the machine? |
| --- | --- |
| LLM & embeddings | only if you point them somewhere other than `127.0.0.1` |
| Transcription | no — the model downloads once, then runs locally |
| **YouTube capture** | **yes, and it is on by default** — `yt-dlp` fetches the video |
| Web fonts | no — Inter, Inter Tight and IBM Plex Mono are vendored in `frontend/src/fonts/` |

So "local-first" is accurate. The only remaining row is YouTube capture, which
is a real feature rather than an accident — turning it off
(`youtube.max_duration_min = 0`) makes the report say nothing leaves the
machine.

The web fonts used to be the second row: they were fetched from
`fonts.googleapis.com` on every page load, which is why `tests/test_no_remote_assets.py`
exists. It reads the **source** rather than the build, because the build is an
artifact that gets regenerated, cleaned and served from somewhere else — a guard
that depends on it stops running the moment `dist` is deleted. It has no
allowlist: the app is local-first and has no origin it legitimately needs.

A loopback or `.local` address counts as local — Ollama on `127.0.0.1` is a
socket, not a phone home — but a LAN address like `192.168.x.x` does leave the
machine, so the classifier reads the address rather than the scheme.

## Redacted export

```json
POST /api/export  {"redact": true, "names": ["Alice", "Bob"]}
```

Returns every note as one markdown bundle with emails, phone numbers, card
numbers, API keys and URLs replaced by placeholders, plus a count of what was
found. Nothing is written back — the export renders from the database and
redacts that string.

**Person names are not pattern-matched.** `Alice`, `Prof. Ng` and "my brother
Raj" are not separable from ordinary words by regex, and a guessing pass mangles
notes while giving the comfortable impression that names were handled. You pass
the names you know; they become stable `[person-1]` / `[person-2]` placeholders so
a sentence still reads.

Short digit runs are left alone on purpose: versions, percentages, years and PR
numbers are what notes are *for*, and the addresses that matter are longer.

## Forgetting

`POST /api/forget {"minutes": 15, "confirm": true}` deletes the last fifteen
minutes: notes, tasks and activity created inside the window. Without
`confirm` it answers 409 with a preview of titles — you cannot confirm "3 rows",
but you can confirm three things you recognise.

It only deletes what was **created** in the window. A note you had for six
months and edited five minutes ago is not "the last fifteen minutes", and a
panic button that could destroy it will eventually do it. Tasks attached to
older notes do go, because they were created recently.

Every call is audited (`GET /api/audit`). An empty window is not a prompt —
there is nothing to confirm, so it succeeds and writes nothing.

## Hooks

`~/.config/fleeting/hooks/*.py`, each defining `on_<event>(payload)` functions.
App runs them as subprocesses on note writes, task changes and daily-log rewrites.

```python
# ~/.config/fleeting/hooks/desk_log.py
def on_note_created(payload):
    ...  # payload is the note dict
```

A hook that raises is logged and skipped — a note never fails to save because a
script has a typo — and one that hangs is killed after 10 seconds. The payload
arrives as JSON on stdin, never as a shell string. Return values are ignored: to
change something, edit the database. See `hooks/README.md` for the event table
and `hooks/example_desk_log.py` for a working one.

These are your own code with your own permissions. Theme packs cannot install
them.

To trigger a **command** instead of writing Python, copy `hooks/run_command.py`
into the same folder and declare actions in `~/.config/fleeting/actions.toml`:

```toml
[[action]]
event = "note.created"
command = ["notify-send", "Fleeting", "{title}"]
```

`command` is an argv list, never a shell string — `{title}` is substituted into an
argv *element*, so a note containing `$(rm -rf ~)` is an argument, not a command.

## Themes & prompt packs

A pack is one JSON file — a `theme` of CSS custom properties and a `prompts`
object. Settings → **Themes & Packs** lists what it finds and installs it in one
click; nothing is downloaded, and no pack can write anything except
`writing.style_guide` and `llm.preferred_tags`.

Three ship in `packs/`: **Midnight** (dark), **Daylight** (a cool accent), and
**Zettelkasten** (prompts only). They load automatically from the repo, and your
own copy of one in `~/.config/fleeting/packs/` shadows it by name — which is the
supported way to edit a bundled pack.

A pack is untrusted input, so two gates hold: theme keys must be CSS custom
properties with simple values (a `}` would close the rule and rewrite the rest of
the sheet), and prompt keys must be in a two-entry whitelist. A malformed file is
reported next to the packs that did load rather than dropped silently.

Copy `packs/midnight.json` to `~/.config/fleeting/packs/` and edit it to see the
whole format in one file.

## What it needs

`GET /api/preflight` — also in **Settings → System** — checks the vault, the
LLM provider, `ffmpeg`, `yt-dlp` and `hyprctl`, and tells you what to install for
whatever is missing. Each probe runs the tool rather than checking `PATH`, because
a stale PATH entry points at a file that cannot execute.

Only the vault is marked required: without it captures have nowhere to go.
A missing `ffmpeg` costs you voice memos, not the app, and reporting optional
gaps as failures just teaches you to ignore the panel.

Model selection lives in Settings → AI (`enrich_model` and friends). An existing
Obsidian vault needs no importer — point `paths.vault_dir` at it, since the vault
watcher already traverses the directory recursively for `.md`.

## Other local AI clients (MCP)

An MCP server so another local AI client can search the same notes, over stdio:

```jsonc
// e.g. ~/.config/your-client/mcp.json
{
  "mcpServers": {
    "fleeting": { "command": "uv", "args": ["run", "--project", "/path/to/fleeting/backend", "fleeting-mcp"] }
  }
}
```

Three tools — `search_notes`, `search_tasks`, `get_note` — and nothing that
writes. No API key, no network: it reads the same SQLite file the app does.

## Tests

```bash
cd backend && uv run pytest                  # 632 tests, ~7s (a floor suite: 233 are one-per-route)
cd frontend && bun run test                  # 188 tests, ~1s
cd frontend && bun run test:e2e              # 14 browser tests, needs the seeded demo
```

Patching it? [CONTRIBUTING.md](CONTRIBUTING.md) has the few rules that are not
obvious from the code — they are the ones that have already caused data loss, a
crash at boot, or a card that silently went stale.

## Where it's going

Each version is one theme, landed whole. Bundles are worked in the order that
helps most, not strictly by number — 0.18 came before several lower-numbered
ones because tooling and tests unblock everything after them.

**Shipped — 0.3 through 0.9:**

| Version | Theme |
| --- | --- |
| 0.3 | Capture & dictation ergonomics |
| 0.4 | Notes, Inbox & organisation |
| 0.5 | Tasks & day planning |
| 0.6 | Search & recall |
| 0.7 | Timeline & activity depth |
| 0.8 | Reports, insights & charts |
| 0.9 | Assistant & AI quality |
| 0.18 | DX, testing, ops & ecosystem |

**In progress — 0.11:** privacy, security and portability — keyring-backed API
keys, a panic button, per-source retention, an audit log, a network-egress
self-check, encrypted backup and restore.

**Still to come**, in no particular order: the desktop and CLI bundle (0.12),
vault and sharing (0.10), UI polish, theming,
a11y and i18n (0.13), capture-pipeline reliability (0.14), knowledge work and
writing (0.15), habits and notifications (0.16), cross-device and mobile sync
(0.17), a public contributor guide, a query console over the SQLite schema, an
MCP server so other local AI clients can search notes read-only, and a first-run
setup check.

Everything above is a plan, not a promise.
