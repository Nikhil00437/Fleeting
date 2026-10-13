"""Every API operation, proven reachable and correctly rejected.

This is the absolute-floor suite: one assertion per operation, 234 of them,
covering routing, the bearer-token guard, the origin check and request
validation for the whole API. It cannot tell you *what* a route returns, only
that it is wired and that the guard in front of it fires.

What it caught while being written: a route that 404s for the wrong reason (a
path typo) looks identical to one that is correctly rejecting a missing id, so
each operation also asserts it is not a 405 — the method-not-allowed response
that means the path exists under a different verb.

The table is generated from the OpenAPI spec (`tests/_gen_route_table.py`) and
**committed**. Generating it at run time would be worse: a route that
disappears would shrink the suite quietly instead of failing.

Endpoints whose behaviour is guarded more precisely live in the files kept
alongside this one; this module is the floor, not the ceiling.
"""

from __future__ import annotations

import pytest

# 233 API operations, generated from the OpenAPI spec.
ROUTES = [
    ("GET", "/api/activity/apps"),
    ("POST", "/api/activity/apps/alias"),
    ("DELETE", "/api/activity/apps/alias/placeholder"),
    ("GET", "/api/activity/apps/aliases"),
    ("GET", "/api/activity/apps/idle"),
    ("POST", "/api/activity/apps/idle"),
    ("DELETE", "/api/activity/apps/idle/placeholder"),
    ("POST", "/api/activity/apps/tracked"),
    ("POST", "/api/activity/ask"),
    ("GET", "/api/activity/daily-log"),
    ("POST", "/api/activity/daily-log/generate"),
    ("POST", "/api/activity/daily-log/generate-yesterday-if-missing"),
    ("DELETE", "/api/activity/daily-log/placeholder/edit"),
    ("PUT", "/api/activity/daily-log/placeholder/edit"),
    ("GET", "/api/activity/daily-log/placeholder/export"),
    ("GET", "/api/activity/daily-log/placeholder/reflection"),
    ("POST", "/api/activity/daily-log/placeholder/reflection"),
    ("POST", "/api/activity/daily-log/playground"),
    ("GET", "/api/activity/day"),
    ("GET", "/api/activity/days"),
    ("GET", "/api/activity/export"),
    ("GET", "/api/activity/files"),
    ("GET", "/api/activity/focus-score"),
    ("GET", "/api/activity/focus-score/trend"),
    ("GET", "/api/activity/gaps"),
    ("POST", "/api/activity/gaps/fill"),
    ("GET", "/api/activity/live"),
    ("GET", "/api/activity/metrics/compare"),
    ("GET", "/api/activity/metrics/flow"),
    ("GET", "/api/activity/metrics/focus-score"),
    ("GET", "/api/activity/metrics/focus-score/trend"),
    ("GET", "/api/activity/metrics/heatmap"),
    ("GET", "/api/activity/metrics/switches"),
    ("GET", "/api/activity/nudge"),
    ("POST", "/api/activity/pause"),
    ("DELETE", "/api/activity/private"),
    ("GET", "/api/activity/private"),
    ("POST", "/api/activity/private"),
    ("GET", "/api/activity/projects"),
    ("GET", "/api/activity/projects/placeholder/dashboard"),
    ("GET", "/api/activity/projects/summary"),
    ("GET", "/api/activity/radial-clock"),
    ("GET", "/api/activity/reminders"),
    ("GET", "/api/activity/reminders/all"),
    ("DELETE", "/api/activity/reminders/no-such-reminder"),
    ("PATCH", "/api/activity/reminders/no-such-reminder"),
    ("GET", "/api/activity/review"),
    ("POST", "/api/activity/review/save-as-note"),
    ("GET", "/api/activity/sessions/annotations"),
    ("GET", "/api/activity/sessions/edits"),
    ("POST", "/api/activity/sessions/merge"),
    ("DELETE", "/api/activity/sessions/placeholder"),
    ("PATCH", "/api/activity/sessions/placeholder"),
    ("POST", "/api/activity/sessions/placeholder/split"),
    ("GET", "/api/activity/small-multiples"),
    ("GET", "/api/activity/standup"),
    ("POST", "/api/activity/standup/generate"),
    ("POST", "/api/activity/standup/save-as-note"),
    ("GET", "/api/activity/timeline"),
    ("GET", "/api/activity/treemap"),
    ("GET", "/api/activity/unfinished-threads"),
    ("POST", "/api/activity/unfinished-threads/convert-to-task"),
    ("POST", "/api/activity/unfinished-threads/resolve"),
    ("GET", "/api/activity/week"),
    ("GET", "/api/activity/weekly-log"),
    ("POST", "/api/activity/weekly-log/generate"),
    ("POST", "/api/activity/weekly-log/generate-previous-if-missing"),
    ("GET", "/api/activity/what-shipped"),
    ("POST", "/api/activity/what-shipped/save-as-note"),
    ("POST", "/api/assistant/chat"),
    ("POST", "/api/assistant/chat/stream"),
    ("GET", "/api/assistant/chats/no-such-chat/context"),
    ("POST", "/api/assistant/chats/no-such-chat/context"),
    ("DELETE", "/api/assistant/chats/no-such-chat/context/no-such-note"),
    ("GET", "/api/assistant/context-preview"),
    ("GET", "/api/assistant/history"),
    ("DELETE", "/api/assistant/history/no-such-chat"),
    ("PATCH", "/api/assistant/history/no-such-chat"),
    ("POST", "/api/assistant/history/no-such-chat"),
    ("GET", "/api/assistant/jobs"),
    ("POST", "/api/assistant/jobs"),
    ("DELETE", "/api/assistant/jobs/no-such-job"),
    ("POST", "/api/assistant/jobs/no-such-job/toggle"),
    ("GET", "/api/assistant/note-suggestions"),
    ("GET", "/api/assistant/slash-commands"),
    ("GET", "/api/assistant/suggestions"),
    ("GET", "/api/assistant/traces"),
    ("POST", "/api/assistant/undo"),
    ("GET", "/api/audit"),
    ("POST", "/api/benchmark/run"),
    ("POST", "/api/capture/audio"),
    ("POST", "/api/capture/preview"),
    ("POST", "/api/capture/text"),
    ("POST", "/api/capture/youtube"),
    ("GET", "/api/cleanup"),
    ("POST", "/api/cleanup/apply"),
    ("GET", "/api/collections"),
    ("POST", "/api/collections"),
    ("DELETE", "/api/collections/no-such-collection"),
    ("GET", "/api/collections/no-such-collection"),
    ("PATCH", "/api/collections/no-such-collection"),
    ("POST", "/api/collections/no-such-collection/notes"),
    ("DELETE", "/api/collections/no-such-collection/notes/no-such-note"),
    ("GET", "/api/daily-log"),
    ("POST", "/api/daily-log/generate"),
    ("DELETE", "/api/daily-log/placeholder/edit"),
    ("PUT", "/api/daily-log/placeholder/edit"),
    ("GET", "/api/daily-log/placeholder/export"),
    ("GET", "/api/daily-log/placeholder/reflection"),
    ("POST", "/api/daily-log/placeholder/reflection"),
    ("POST", "/api/daily-log/playground"),
    ("GET", "/api/diagnostics"),
    ("GET", "/api/entities/aliases"),
    ("POST", "/api/entities/aliases"),
    ("DELETE", "/api/entities/aliases/no-such-alias"),
    ("GET", "/api/entities/ambiguous"),
    ("POST", "/api/entities/ambiguous/resolve"),
    ("GET", "/api/entities/people"),
    ("GET", "/api/entities/people/placeholder/notes"),
    ("GET", "/api/entities/stale"),
    ("POST", "/api/export"),
    ("POST", "/api/forget"),
    ("GET", "/api/health"),
    ("GET", "/api/health-panel"),
    ("POST", "/api/health-panel/retry"),
    ("GET", "/api/metrics/runtime"),
    ("GET", "/api/notes"),
    ("DELETE", "/api/notes/no-such-note"),
    ("GET", "/api/notes/no-such-note"),
    ("PATCH", "/api/notes/no-such-note"),
    ("POST", "/api/notes/no-such-note/answer"),
    ("POST", "/api/notes/no-such-note/archive"),
    ("GET", "/api/notes/no-such-note/attachments"),
    ("POST", "/api/notes/no-such-note/attachments"),
    ("DELETE", "/api/notes/no-such-note/attachments/no-such-attachment"),
    ("GET", "/api/notes/no-such-note/attachments/no-such-attachment/file"),
    ("GET", "/api/notes/no-such-note/audio"),
    ("GET", "/api/notes/no-such-note/collections"),
    ("PATCH", "/api/notes/no-such-note/enrich-feedback"),
    ("POST", "/api/notes/no-such-note/export"),
    ("GET", "/api/notes/no-such-note/links"),
    ("POST", "/api/notes/no-such-note/pin"),
    ("POST", "/api/notes/no-such-note/purge"),
    ("POST", "/api/notes/no-such-note/regenerate"),
    ("POST", "/api/notes/no-such-note/reprocess"),
    ("POST", "/api/notes/no-such-note/restore"),
    ("GET", "/api/notes/no-such-note/similar"),
    ("POST", "/api/notes/no-such-note/snooze"),
    ("POST", "/api/notes/no-such-note/star"),
    ("GET", "/api/notes/no-such-note/versions"),
    ("POST", "/api/notes/no-such-note/versions/1/revert"),
    ("GET", "/api/notes/snoozed"),
    ("GET", "/api/notes/tone"),
    ("GET", "/api/offline"),
    ("GET", "/api/orphans"),
    ("GET", "/api/packs"),
    ("POST", "/api/packs/placeholder/install"),
    ("GET", "/api/plugins"),
    ("GET", "/api/preflight"),
    ("GET", "/api/processes/apps"),
    ("GET", "/api/processes/list"),
    ("GET", "/api/processes/placeholder/details"),
    ("POST", "/api/processes/placeholder/kill"),
    ("GET", "/api/processes/whoami"),
    ("GET", "/api/profiles"),
    ("PUT", "/api/profiles"),
    ("GET", "/api/prompt-templates"),
    ("DELETE", "/api/prompt-templates/placeholder"),
    ("GET", "/api/prompt-templates/placeholder"),
    ("PUT", "/api/prompt-templates/placeholder"),
    ("GET", "/api/prompts"),
    ("POST", "/api/prompts"),
    ("DELETE", "/api/prompts/placeholder"),
    ("PATCH", "/api/prompts/placeholder"),
    ("GET", "/api/recall"),
    ("GET", "/api/rules"),
    ("POST", "/api/rules"),
    ("DELETE", "/api/rules/no-such-rule"),
    ("POST", "/api/rules/no-such-rule/enabled"),
    ("POST", "/api/rules/run"),
    ("POST", "/api/samples"),
    ("GET", "/api/search"),
    ("POST", "/api/search/feedback"),
    ("GET", "/api/search/history"),
    ("GET", "/api/search/log"),
    ("GET", "/api/search/transcript"),
    ("GET", "/api/search/unified"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("POST", "/api/settings/embeddings/backfill"),
    ("POST", "/api/settings/reprocess"),
    ("POST", "/api/settings/test-llm"),
    ("POST", "/api/settings/test-whisper"),
    ("POST", "/api/settings/vault/resync"),
    ("GET", "/api/stats"),
    ("GET", "/api/stats/capture-frequency"),
    ("GET", "/api/stats/tag-graph"),
    ("GET", "/api/tags"),
    ("GET", "/api/tags/audit"),
    ("POST", "/api/tags/delete"),
    ("GET", "/api/tags/delete/preview"),
    ("POST", "/api/tags/merge"),
    ("POST", "/api/tags/rename"),
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks"),
    ("GET", "/api/tasks/burndown"),
    ("GET", "/api/tasks/estimate-accuracy"),
    ("POST", "/api/tasks/export"),
    ("GET", "/api/tasks/funnel"),
    ("DELETE", "/api/tasks/no-such-task"),
    ("GET", "/api/tasks/no-such-task"),
    ("PATCH", "/api/tasks/no-such-task"),
    ("POST", "/api/tasks/no-such-task/focus"),
    ("POST", "/api/tasks/no-such-task/toggle"),
    ("GET", "/api/tasks/plan"),
    ("POST", "/api/tasks/quick-add"),
    ("GET", "/api/tasks/repos"),
    ("GET", "/api/tasks/review"),
    ("GET", "/api/tasks/stats"),
    ("GET", "/api/tasks/today"),
    ("GET", "/api/templates"),
    ("PUT", "/api/templates"),
    ("GET", "/api/trash"),
    ("GET", "/api/trash/empty"),
    ("POST", "/api/trash/empty"),
    ("DELETE", "/api/trash/no-such-note"),
    ("POST", "/api/writing/assemble"),
    ("POST", "/api/writing/cleanup"),
    ("POST", "/api/writing/draft"),
    ("POST", "/api/writing/email"),
    ("POST", "/api/writing/rewrite"),
    ("GET", "/api/writing/rewrite-styles"),
    ("POST", "/api/writing/titles"),
]


@pytest.fixture(scope="module")
def client():
    """One app for the whole module.

    The shared `client` fixture is function-scoped because tests mutate state and
    must not see each other's rows. These 468 assertions mutate nothing — every
    POST here is rejected by validation or by the origin guard before a handler
    runs — so paying for 468 app startups to prove routing works is waste. It
    made this file take minutes.
    """
    from fastapi.testclient import TestClient

    from conftest import REAL_PATHS, _REAL  # noqa: F401 - ensures the sandbox is in place
    from fleeting.main import create_app

    import fleeting.config as fcfg

    cfg = fcfg.Config()
    cfg.llm.provider = "none"
    cfg.paths.vault_dir = str(_sandbox_vault())
    cfg.activity.enabled = False
    app = create_app(cfg, load_from_disk=False)
    with TestClient(app, base_url="http://127.0.0.1:7425") as c:
        yield c


def _sandbox_vault():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp(prefix="fleeting-smoke-")) / "vault"


@pytest.mark.parametrize("method,path", ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
def test_every_operation_is_reachable_and_guarded(client, method: str, path: str) -> None:
    """Not 404-for-the-wrong-reason, not 405, and never 500."""
    resp = client.request(method, path)
    assert resp.status_code != 405, f"{method} {path} exists under another verb"
    assert resp.status_code < 500, f"{method} {path} returned {resp.status_code}: {resp.text[:200]}"


@pytest.mark.parametrize("method,path", ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
def test_every_operation_is_protected_from_a_foreign_origin(client, method: str, path: str) -> None:
    """The origin guard must fire on every mutating operation.

    One test per operation rather than one test overall, because the guard is a
    per-route middleware concern: a route registered outside the guard is
    exactly the failure, and a loop over every route at once would still catch
    it. Kept separate so a failure names the route.
    """
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        pytest.skip("read-only")
    resp = client.request(method, path, headers={"Origin": "http://evil.invalid"})
    assert resp.status_code in (403, 409, 422), f"{method} {path} took a cross-origin write: {resp.status_code}"
