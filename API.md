# Fleeting HTTP API

Generated from the OpenAPI spec by `scripts/gen_api_docs.py`. Do not edit — `tests/test_api_docs.py` regenerates and compares.

Fleeting 0.1.0 · 217 paths · server `http://127.0.0.1:7425`

The [spec itself](backend/fleeting/api_docs.py) is the source of truth for what the
guards do; this file is an index of what exists.

A local-first capture and memory API. Everything is served on loopback and nothing
is required to leave the machine.

## Stability

`/api` is **additive**. New endpoints and new optional fields may appear in any
release; a field will not be removed or retyped without a major version, and a
removal takes a `/api/v2` prefix rather than happening silently. Endpoints marked
*internal* in the tags below are not covered by that promise — they exist because
the UI needs them, not because they are an interface.

## Authentication

Three independent guards, and knowing only one of them is how a client ends up
misdiagnosing a failure:

1. **Host allow-list.** A request whose `Host` is not the local address is `421`.
   This is DNS-rebinding defence and no amount of authenticating fixes it.
2. **Bearer token** on mutating `/api` calls, when a token is configured. Send
   `Authorization: Bearer <token>`.
3. **Origin check** on mutating `/api` calls. A cross-origin write is `403`; a
   missing `Origin` is a non-browser client and is allowed.

### The token is optional

| situation | writes | reads |
|---|---|---|
| no token configured | allowed | allowed |
| token configured | token required | allowed |
| token configured + `activity.reads_require_token` | token required | token required |

`/api/health` is always exempt, so the app can come up before it has a token.
`/api/events` accepts the token as `?token=` as well, because `EventSource`
cannot set an `Authorization` header; the header is still tried first, since a
query string ends up in proxy logs and shell history.

## Errors

`{"detail": ...}` throughout. `detail` is a string for FastAPI's own errors and
an object for this app's, which always carries an `error` code, a human-readable
`message`, and for destructive calls the `count` and `samples` of what would be
affected. A `409` with `error: "confirmation_required"` is not a failure to be
retried — it is the preview, and re-sending it with `confirm: true` is the next
step.


## Endpoints

### `activity`

Window tracking, timelines, gaps, standups.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/activity/apps` | Known Apps | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/apps/alias` | Set App Alias | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/activity/apps/alias/{from_class}` | Delete App Alias | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/activity/apps/aliases` | App Aliases | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/activity/apps/idle` | App Idle Rules | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/apps/idle` | Set App Idle | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/activity/apps/idle/{app_class}` | Clear App Idle | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/activity/apps/tracked` | Set App Tracked | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/ask` | Ask About Window | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/daily-log` | Get Daily Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/daily-log/generate` | Generate Log | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/daily-log/generate-yesterday-if-missing` | Generate Yesterday | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/daily-log/playground` | Playground Log | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/activity/daily-log/{day}/edit` | Clear Daily Log Edit | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| PUT | `/api/activity/daily-log/{day}/edit` | Edit Daily Log | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |
| GET | `/api/activity/daily-log/{day}/export` | Export Daily Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/daily-log/{day}/reflection` | Get Daily Reflection | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/daily-log/{day}/reflection` | Save Daily Reflection | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/day` | Activity Day | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/days` | Activity Days | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/activity/export` | Export Activity | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/files` | Files Activity | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/files/preview` | Files Preview | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/focus-score` | Metric Focus Score | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/focus-score/trend` | Metric Focus Score Trend | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/gaps` | Activity Gaps | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/gaps/fill` | Fill Gap | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/live` | Live Session | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/activity/metrics/compare` | Metric Compare | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/metrics/flow` | Metric Flow | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/metrics/focus-score` | Metric Focus Score | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/metrics/focus-score/trend` | Metric Focus Score Trend | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/metrics/heatmap` | Metric Heatmap | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/metrics/switches` | Metric Switches | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/nudge` | Get Nudge Endpoint | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/pause` | Set Pause | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/activity/private` | Stop Private | 200 — OK, 204, 401 — token required, 421 — foreign Host |
| GET | `/api/activity/private` | Private State | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/private` | Start Private | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/projects` | Activity Projects | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/projects/summary` | Activity Projects Summary | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/activity/projects/{project}/dashboard` | Activity Project Dashboard | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/radial-clock` | Activity Radial Clock | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/reminders` | List Reminders | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/reminders/all` | All Reminders | 200 — OK, 421 — foreign Host, 423 — app is locked |
| DELETE | `/api/activity/reminders/{reminder_id}` | Drop Reminder | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| PATCH | `/api/activity/reminders/{reminder_id}` | Patch Reminder | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/activity/review` | Get Periodic Review | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/review/save-as-note` | Save Periodic Review As Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/sessions/annotations` | Session Annotations | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/sessions/edits` | Session Edit Trail | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/sessions/merge` | Merge Sessions | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/activity/sessions/{session_id}` | Delete Session | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| PATCH | `/api/activity/sessions/{session_id}` | Relabel Session | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/activity/sessions/{session_id}/split` | Split Session | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/small-multiples` | Activity Small Multiples | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/standup` | Get Standup | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/standup/generate` | Generate Standup Endpoint | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/standup/save-as-note` | Save Standup As Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/timeline` | Activity Timeline | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/treemap` | Activity Treemap | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/unfinished-threads` | Get Threads Endpoint | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/activity/unfinished-threads/convert-to-task` | Convert Thread To Task Endpoint | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/unfinished-threads/resolve` | Resolve Thread Endpoint | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/week` | Activity Week | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/activity/weekly-log` | Get Weekly Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/weekly-log/generate` | Generate Weekly | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/weekly-log/generate-previous-if-missing` | Generate Previous Weekly | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| GET | `/api/activity/what-shipped` | Get What Shipped Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/activity/what-shipped/save-as-note` | Save What Shipped As Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `assistant`

Tool calls. Destructive tools soft-delete (#456).

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| POST | `/api/assistant/chat` | Chat | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/assistant/chat/stream` | Chat Stream | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/assistant/chats/{chat_id}/context` | Pinned Context | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/assistant/chats/{chat_id}/context` | Pin Into Context | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/assistant/chats/{chat_id}/context/{note_id}` | Unpin From Context | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/assistant/context-preview` | Context Preview | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/assistant/history` | Chat History | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/assistant/history/{chat_id}` | Delete Chat History | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| PATCH | `/api/assistant/history/{chat_id}` | Pin Chat History | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/assistant/history/{chat_id}` | Save Chat History | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/assistant/jobs` | List Scheduled Jobs | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/assistant/jobs` | Create Scheduled Job | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/assistant/jobs/{job_id}` | Remove Scheduled Job | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/assistant/jobs/{job_id}/toggle` | Toggle Scheduled Job | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/assistant/note-suggestions` | Note Suggestions | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/assistant/slash-commands` | Slash Commands | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/assistant/suggestions` | Suggestions | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/assistant/traces` | Llm Traces | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/assistant/undo` | Undo | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `capture`

Ingest: text, voice, YouTube, files.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| POST | `/api/capture/audio` | Capture Audio | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/capture/preview` | Preview Transcription | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/capture/text` | Capture Text | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/capture/youtube` | Capture Youtube | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `cleanup`

Bulk maintenance. Every call previews before it acts.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/cleanup` | Suggestions | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/cleanup/apply` | Apply | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `collections`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/collections` | List Collections | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/collections` | Create Collection | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/collections/{coll_id}` | Delete Collection | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/collections/{coll_id}` | Get Collection | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| PATCH | `/api/collections/{coll_id}` | Update Collection | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/collections/{coll_id}/notes` | Add Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/collections/{coll_id}/notes/{note_id}` | Remove Note | 200 — OK, 401 — token required, 421 — foreign Host, 422 |

### `daily-log`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/daily-log` | Get Daily Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/daily-log/generate` | Generate Log | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/daily-log/playground` | Playground Log | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/daily-log/{day}/edit` | Clear Daily Log Edit | 200 — OK, 204, 401 — token required, 421 — foreign Host, 422 |
| PUT | `/api/daily-log/{day}/edit` | Edit Daily Log | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |
| GET | `/api/daily-log/{day}/export` | Export Daily Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/daily-log/{day}/reflection` | Get Daily Reflection | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/daily-log/{day}/reflection` | Save Daily Reflection | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `entities`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/entities/aliases` | List Aliases | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/entities/aliases` | Add Alias | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/entities/aliases/{alias}` | Remove Alias | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/entities/ambiguous` | Ambiguous | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/entities/ambiguous/resolve` | Resolve Alias | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/entities/people` | People | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/entities/people/{name}/notes` | Person Notes | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/entities/stale` | Stale | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |

### `export`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| POST | `/api/export` | Export Notes | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `health`

Liveness. Exempt from the token.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/health-panel` | Health Panel | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/health-panel/retry` | Health Panel Retry | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |

### `notes`

Captured notes: list, edit, trash, restore, purge.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/notes` | List Notes | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/snoozed` | List Snoozed | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/notes/tone` | List Notes By Tone | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/notes/{note_id}` | Trash Note | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/notes/{note_id}` | Get Note | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| PATCH | `/api/notes/{note_id}` | Update Note | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/notes/{note_id}/answer` | Answer Clarification | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/archive` | Toggle Archive | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/attachments` | List Attachments | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/attachments` | Upload Attachment | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/notes/{note_id}/attachments/{att_id}` | Remove Attachment | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/notes/{note_id}/attachments/{att_id}/file` | Download Attachment | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/audio` | Get Note Audio | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/collections` | Note Collections | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| PATCH | `/api/notes/{note_id}/enrich-feedback` | Set Enrich Feedback | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/notes/{note_id}/export` | Export Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/links` | Get Note Links | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/pin` | Toggle Pin | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/purge` | Purge Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/regenerate` | Regenerate Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/reprocess` | Reprocess Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/restore` | Restore Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/similar` | Get Similar Notes | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/snooze` | Snooze Note | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/star` | Toggle Star | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/notes/{note_id}/versions` | List Note Versions | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/notes/{note_id}/versions/{version_id}/revert` | Revert Note Version | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/trash` | List Trash | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/trash/empty` | Trash Empty Preview | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/trash/empty` | Trash Empty | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/trash/{note_id}` | Trash Purge | 200 — OK, 401 — token required, 421 — foreign Host, 422 |

### `packs`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/packs` | List Packs Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/packs/{name}/install` | Install Pack Endpoint | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `plugins`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/plugins` | List Plugins Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |

### `privacy`

Forget, retention, export, inventory, audit, backups.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| POST | `/api/forget` | Forget Endpoint | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/retention` | Retention Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/retention/prune` | Prune Retention | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `processes`

Background workers and their state.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/processes/apps` | List Apps | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/processes/list` | List Processes | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/processes/whoami` | Whoami | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/processes/{pid}/details` | Process Details | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/processes/{pid}/kill` | Kill Process | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `profiles`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/profiles` | List Profiles | 200 — OK, 421 — foreign Host, 423 — app is locked |
| PUT | `/api/profiles` | Replace Profiles | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |

### `prompts`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/prompt-templates` | All Templates | 200 — OK, 421 — foreign Host, 423 — app is locked |
| DELETE | `/api/prompt-templates/{target}` | Restore Template | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/prompt-templates/{target}` | One Template | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| PUT | `/api/prompt-templates/{target}` | Edit Template | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |
| GET | `/api/prompts` | All Prompts | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/prompts` | Add Prompt | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| DELETE | `/api/prompts/{prompt_id}` | Remove Prompt | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| PATCH | `/api/prompts/{prompt_id}` | Edit Prompt | 200 — OK, 401 — token required, 421 — foreign Host, 422 |

### `rules`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/rules` | List Rules | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/rules` | Create Rule | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/rules/run` | Run Rules | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| DELETE | `/api/rules/{rule_id}` | Delete Rule | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/rules/{rule_id}/enabled` | Toggle Rule | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `search`

Full-text, semantic and unified search.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/recall` | Recall | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/search` | Search | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/search/feedback` | Search Feedback | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/search/history` | Search History | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/search/log` | Search Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/search/transcript` | Transcript Search Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/search/unified` | Unified | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/stats` | Stats | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/stats/capture-frequency` | Capture Frequency | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/stats/tag-graph` | Tag Graph | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tags` | Tags | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/tags/audit` | Tags Audit | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/tags/delete` | Delete Tag | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tags/delete/preview` | Delete Tag Preview | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/tags/merge` | Merge Tags | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/tags/rename` | Rename Tag | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `settings`

Read and write configuration. Secrets are stored, never returned.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/settings` | Get Settings | 200 — OK, 421 — foreign Host, 423 — app is locked |
| PUT | `/api/settings` | Update Settings | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |
| POST | `/api/settings/embeddings/backfill` | Start Embeddings Backfill | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| POST | `/api/settings/reprocess` | Start Reprocess | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/settings/test-llm` | Test Llm | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/settings/test-whisper` | Test Whisper | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| POST | `/api/settings/vault/resync` | Resync Vault | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |

### `system`

Health, offline status, egress self-check, keyring, encryption.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/audit` | Audit Log | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/backups` | Backups Endpoint | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/backups` | Create Backup | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/backups/{name}/restore` | Restore Backup | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/benchmark/run` | Run Benchmark | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/demo` | Demo Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/diagnostics` | Diagnostics | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/egress` | Egress Self Check | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/encryption` | Encryption Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/events` | Events | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/health` | Health | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/inventory` | Inventory Endpoint | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/keyring` | Keyring Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/lock/lock` | Lock Lock | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| POST | `/api/lock/set` | Lock Set | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/lock/status` | Lock Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/lock/unlock` | Lock Unlock | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/metrics/runtime` | Runtime Metrics | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/offline` | Offline Status | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/orphans` | Orphans | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/preflight` | Preflight | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/samples` | Create Samples | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 423 — app is locked |
| POST | `/api/sql` | Run Sql | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `tasks`

Action items, including those extracted from notes.

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/tasks` | List Tasks | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/tasks` | Create Task | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tasks/burndown` | Get Task Burndown Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tasks/estimate-accuracy` | Get Estimate Accuracy | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/tasks/export` | Export Tasks | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tasks/funnel` | Get Task Funnel Endpoint | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tasks/plan` | Get Week Plan | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/tasks/quick-add` | Quick Add Task | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/tasks/repos` | Get Task Repos | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/tasks/review` | Get Weekly Review | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/tasks/stats` | Get Task Stats | 200 — OK, 421 — foreign Host, 423 — app is locked |
| GET | `/api/tasks/today` | Get Today | 200 — OK, 421 — foreign Host, 423 — app is locked |
| DELETE | `/api/tasks/{task_id}` | Delete Task | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| GET | `/api/tasks/{task_id}` | Get Task | 200 — OK, 421 — foreign Host, 422, 423 — app is locked |
| PATCH | `/api/tasks/{task_id}` | Update Task | 200 — OK, 401 — token required, 421 — foreign Host, 422 |
| POST | `/api/tasks/{task_id}/focus` | Log Focus | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/tasks/{task_id}/toggle` | Toggle Task | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |

### `templates`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| GET | `/api/templates` | List Templates | 200 — OK, 421 — foreign Host, 423 — app is locked |
| PUT | `/api/templates` | Replace Templates | 200 — OK, 401 — token required, 409 — confirmation required, 421 — foreign Host, 422 |

### `writing`

| Method | Path | Summary | Codes |
| --- | --- | --- | --- |
| POST | `/api/writing/assemble` | Assemble | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/writing/cleanup` | Cleanup | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/writing/draft` | Draft | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/writing/email` | Email | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| POST | `/api/writing/rewrite` | Rewrite | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
| GET | `/api/writing/rewrite-styles` | Rewrite Styles | 200 — OK, 421 — foreign Host, 423 — app is locked |
| POST | `/api/writing/titles` | Titles | 200 — OK, 401 — token required, 403 — cross-origin write, or read-only demo, 409 — confirmation required, 421 — foreign Host, 422, 423 — app is locked |
