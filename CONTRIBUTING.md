# Contributing

Short on purpose. Nobody reads a wall of process before their first patch.

## Running it

```bash
./scripts/install.sh          # backend venv + frontend deps
./scripts/dev-restart.sh      # uvicorn on 127.0.0.1:7425
cd frontend && bun run dev    # vite on :5173, proxies /api
```

Three gates, all local, all fast:

```bash
cd backend && uv run pytest -q                       # 632, ~7s
cd frontend && bun run test                          # 188, ~1s
cd frontend && bun run build                         # tsc -b && vite build

cd frontend && bun run test:e2e                      # 14 browser tests
```

`bun run test:e2e` seeds a throwaway `.demo/` database and serves the app on
:7427. It is hermetic — no model, no activity collector, no vault writes — so it
needs nothing but the repo.

## The test suite is a floor, not a ceiling

820 tests, deliberately, and the shape matters more than the count.

- **`tests/test_routes_smoke.py` holds 233 of them** — one assertion for each of
  the 233 API operations, proving every route is wired, guarded by the bearer
  token and the origin check, and not returning 500. The table is generated from
  the OpenAPI spec by `tests/_gen_route_table.py` and **committed**, so a route
  that disappears fails the suite instead of quietly shrinking it.
- **Security, isolation and doc guards are kept whole** — `test_auth`,
  `test_csrf`, `test_no_real_writes`, `test_no_remote_assets`,
  `test_readme_roadmap`, `test_architecture_doc`, `test_contributing_guide`.
  These have caught real drift repeatedly and are the cheapest insurance here.
- **`test_markdown_properties.py` is a sampled corpus**, not the full
  cross-product. Every fragment still appears; the axes that do not interact are
  exhausted separately.

What was cut, and what it costs: roughly 200 granular tests per feature. The
floor suite found two real 500s within a minute of being written
(`/api/activity/standup` and `GET /api/prompt-templates/{target}`), both of which
had been broken in the shipped app. But it cannot tell you *what* a route
returns — only that it is wired. **A regression in a response body shape, a
failure path, or a UI component will not be caught here.** If you change a route
and something downstream looks wrong, the route smoke test will stay green. Add
a test when you fix something, and expect to be the only one.

## Before you open a PR

**Write the test first, and watch it fail.** Not as ritual — because a test
written after the code tends to assert what the code happens to do, and passes
against a broken implementation.

**Then check the test has teeth by breaking the code on purpose.** Delete the
guard, rename the event, replace the median with a mean. If the suite stays
green, the test was not testing anything. This has found more real bugs than
reading the diff ever did, and it matters more here than it used to: with a
floor suite, an unmarked test is the *only* test.

**One logical change per commit.** Conventional commits: `feat(inbox):`,
`fix(processes):`, `refactor(ui):`, `chore:`, `docs:`.

## Rules that are not obvious from the code

**Never bind a config path by value at import.** `from ..config import
AUDIO_DIR` cannot be redirected afterwards, and that is how tests once wrote to
the user's real data. Read the module attribute at call time.

**A `Config` must set `paths.vault_dir`.** Tests that build their own `Config()`
without it mirrored notes into the real vault, which the running app then
imported back as captures. Prefer the `client` fixture; it already does this.

**Anything in a demo or fixture environment must write its own config.** XDG
variables relocate the database but not `paths.vault_dir`, and do not disable the
activity collector or the LLM. Defaults otherwise attach themselves to
`~/Documents/FleetingVault`.

**Migrations are append-only, and some work runs on every boot.** `MIGRATIONS` in
`db.py` are applied once and tracked in `schema_version`; `_migrate_guarded_columns`,
`_migrate_activity_index` and `_migrate_action_items` run every time, unversioned.
That last one is a data migration wearing a boot hook's clothes, so it has to stay
idempotent against notes `insert_note` has already promoted — it used to add a
copy of every task on every restart.

**Every write the UI must see live publishes an event.** A `bus.publish` with no
branch in `frontend/src/components/serverEvents.ts` fails silently: the card sits
stale until the user navigates away and back. This is the single most common bug
in the codebase.

**Secrets never reach a response.** The settings API reports only *whether* a key
is set. The diagnostics bundle redacts by denylist across the whole config — a
field whose name contains key, token, secret or password — because a whitelist
needs extending whenever a field is added, and the forgotten one is the one that
leaks.

**Two timestamp frames.** `created_at` and `processed_at` are UTC ISO; sessions
and "today" are local. Comparing `ts[:10]` to a local date puts completions on
the wrong side of local midnight. Route day boundaries through
`calendar_svc.date_tag`.

## Picking up work

Anything labelled `good first issue` is work where the design is settled and the
task is mechanical — a missing reducer branch, a test whose assertion cannot
fail, a module with no coverage at all. `help wanted` means the same, except
someone has to own a decision rather than just make a change.

If you want to work on something not yet labelled, open an issue first. The
capture pipeline and the metrics are the parts where a wrong change is hardest to
see, so a conversation before the patch saves both of us a round trip.
