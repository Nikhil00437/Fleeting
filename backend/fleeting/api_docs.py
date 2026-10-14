"""#293: the OpenAPI description of the public API.

The spec already existed — FastAPI generates one — but it described an API that
did not exist as far as anyone using it could tell. There was no description, no
server URL, and, most importantly, **no declared security scheme**: the document
said nothing about the three guards that actually decide whether a request
succeeds. A client generated from it would have discovered `401` and `421` in
production.

So the spec now declares:

- **What this is** — a local-first HTTP API on loopback, and the stability promise
  (`/api` is additive; a removal is a breaking change and takes a version prefix).
- **The token, and that it is optional** — required for writes, optional for reads
  unless `activity.reads_require_token` is on, and absent entirely when no token is
  configured. Saying "optional" is the whole point: a reader who is told "you need
  a token" and finds none is worse off than one who was told when.
- **The guards that are not tokens** — a foreign `Host` is `421` and a cross-origin
  write is `403`, and neither is fixed by authenticating correctly. A client that
  knows only about the bearer token will misdiagnose both.

These strings are the claim; `test_api_docs.py` checks that the prose and the
middleware still agree.
"""

from __future__ import annotations

DESCRIPTION = """\
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
"""

TAGS = [
    {"name": "health", "description": "Liveness. Exempt from the token."},
    {"name": "notes", "description": "Captured notes: list, edit, trash, restore, purge."},
    {"name": "tasks", "description": "Action items, including those extracted from notes."},
    {"name": "capture", "description": "Ingest: text, voice, YouTube, files."},
    {"name": "search", "description": "Full-text, semantic and unified search."},
    {"name": "settings", "description": "Read and write configuration. Secrets are stored, never returned."},
    {"name": "activity", "description": "Window tracking, timelines, gaps, standups."},
    {"name": "privacy", "description": "Forget, retention, export, inventory, audit, backups."},
    {"name": "processes", "description": "Background workers and their state."},
    {"name": "system", "description": "Health, offline status, egress self-check, keyring, encryption."},
    {"name": "assistant", "description": "Tool calls. Destructive tools soft-delete (#456)."},
    {"name": "cleanup", "description": "Bulk maintenance. Every call previews before it acts."},
    {"name": "internal", "description": "For the UI. Not part of the stability promise."},
]