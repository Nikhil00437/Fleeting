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

## Tests

```bash
cd backend && uv run pytest                  # 235 tests
cd frontend && npx vitest run                # 70 tests
```

## Ideas for v2

- Weekly digest note (auto-generated Sunday summary of the daily logs)
- Real local embeddings instead of the offline n-gram fallback (see
  `services/embeddings.py` — `LocalHashVectorizer` is character-3-gram hashing,
  so it catches typos and short queries but not paraphrase; pointing
  `[llm]` at Ollama's `nomic-embed-text` gets true semantic recall)
- Browser extension: capture selected text with one click
- AFK detection via real wayland idle protocol instead of cursor heuristic
