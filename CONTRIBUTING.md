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
cd backend && uv run pytest -q                       # ~5.8k, ~70s
cd frontend && bun run test                          # ~535, ~10s
cd frontend && bun run build                         # tsc -b && vite build

cd frontend && bun run test:e2e                      # 14 browser tests
```

`bun run test:e2e` seeds a throwaway `.demo/` database and serves the app on
:7427. It is hermetic — no model, no activity collector, no vault writes — so it
needs nothing but the repo.

## Before you open a PR

**Write the test first, and watch it fail.** Not as ritual — because a test
written after the code tends to assert what the code happens to do, and passes
against a broken implementation. Several tests here were written, mutated the
implementation, and turned out to be rubber stamps.

**Then check the test has teeth by breaking the code on purpose.** Delete the
guard, rename the event, replace the median with a mean. If the suite stays
green, the test was not testing anything. This has found more real bugs this
session than reading the diff ever did.

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
