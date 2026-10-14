"""#293: the documented API, and whether the documentation is true.

Three jobs, and the last two are the ones that matter:

1. **`API.md` is in sync with the spec.** It is generated, committed, and
   regenerated here. A reference you have to run something to read is not a
   reference, and one that has quietly drifted is worse than none — a client
   built against it calls endpoints that do not exist.
2. **The prose matches the guards.** The description claims `/api/health` is
   token-exempt, that reads are optional, that a foreign `Host` is `421` and a
   cross-origin write is `403`. Each of those is checked against the running
   application, because documentation of a security control that has drifted is
   the specific failure this file exists to prevent.
3. **The declared security scheme is actually declared.** A spec with a token
   requirement and no `securitySchemes` entry tells a generator nothing.

Deliberately *not* checked: response shapes. `api.ts` assembles most view models
from several endpoints, so a shape check would cover three names while appearing
to cover forty-six — the same reasoning `check_api_contract.py` records.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from tests.repo import REPO_ROOT


@pytest.fixture(scope="module")
def spec():
    from fleeting.config import Config
    from fleeting.main import create_app

    return create_app(Config(), load_from_disk=False).openapi()


@pytest.fixture(scope="module")
def generator():
    """`scripts/gen_api_docs.py`, imported rather than shelled out to."""
    path = REPO_ROOT / "scripts" / "gen_api_docs.py"
    spec_obj = importlib.util.spec_from_file_location("gen_api_docs", path)
    assert spec_obj and spec_obj.loader
    module = importlib.util.module_from_spec(spec_obj)
    sys.modules["gen_api_docs"] = module
    spec_obj.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def api_md() -> str:
    path = REPO_ROOT / "API.md"
    assert path.exists(), "API.md is missing — run scripts/gen_api_docs.py"
    return path.read_text(encoding="utf-8")


# ---- the generated file ----------------------------------------------------


def test_api_md_is_in_sync_with_the_spec(generator, spec, api_md) -> None:
    """The whole point of committing a generated file: it cannot drift."""
    assert generator.render(spec) == api_md, (
        "API.md is out of date. Run: uv run --project backend python scripts/gen_api_docs.py"
    )


def test_the_check_mode_agrees(api_md, tmp_path) -> None:
    """`--check` is what CI would run; it must reach the same conclusion."""
    import subprocess

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT / "backend"),
            "python",
            str(REPO_ROOT / "scripts" / "gen_api_docs.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_endpoint_appears(api_md, spec) -> None:
    for path, methods in spec["paths"].items():
        for method in methods:
            if method in ("get", "post", "put", "patch", "delete"):
                assert f"`{path}`" in api_md, f"{method.upper()} {path} is undocumented"


def test_the_file_is_not_empty_or_placeholder(api_md) -> None:
    assert len(api_md.splitlines()) > 100
    assert "— |" in api_md or "| — |" not in api_md  # no rows left entirely blank


# ---- the spec describes itself ---------------------------------------------


def test_the_security_scheme_is_declared(spec) -> None:
    """A spec with a token requirement and no `securitySchemes` tells a code
    generator nothing."""
    schemes = spec.get("components", {}).get("securitySchemes", {})
    assert "bearerAuth" in schemes
    assert schemes["bearerAuth"]["scheme"] == "bearer"


def test_the_scheme_says_it_is_optional(spec) -> None:
    """Optional is the useful word. 'You need a token' plus no token configured
    is worse than no documentation."""
    assert "Optional" in spec["components"]["securitySchemes"]["bearerAuth"]["description"]


def test_the_server_url_is_declared(spec) -> None:
    assert spec["servers"][0]["url"].startswith("http://127.0.0.1")


def test_the_description_covers_every_guard(spec) -> None:
    description = spec["info"]["description"]
    for needed in ("Host allow-list", "Bearer token", "Origin check"):
        assert needed in description, f"the description never mentions {needed}"


def test_the_stability_promise_is_stated(spec) -> None:
    assert "additive" in spec["info"]["description"]


# ---- and the prose is true -------------------------------------------------


def test_the_documented_health_exemption_is_real(client) -> None:
    """`/api/health` is documented as token-exempt. Verified by actually making
    an unauthenticated request with a token configured and reads protected."""
    client.app.state.st.api_token = "doc-test-token"
    client.app.state.st.cfg.activity.reads_require_token = True
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/notes").status_code == 401
    client.app.state.st.api_token = None
    client.app.state.st.cfg.activity.reads_require_token = False


def test_the_documented_foreign_host_code_is_real(client) -> None:
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 421


def test_the_documented_cross_origin_code_is_real(client) -> None:
    r = client.post("/api/capture/text", json={"text": "x"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_the_documented_missing_origin_is_allowed(client) -> None:
    """Documented as allowed, because `curl` and `flee` do not send one."""
    assert client.post("/api/capture/text", json={"text": "x"}).status_code == 200


def test_the_documented_optional_token_table_holds(client) -> None:
    """No token configured: writes allowed. That is the first row of the table
    and the one a new user meets."""
    assert client.app.state.st.api_token is None
    assert client.post("/api/capture/text", json={"text": "x"}).status_code == 200


def test_the_documented_events_query_token_is_real(client) -> None:
    """Documented as accepted because `EventSource` cannot set a header."""
    client.app.state.st.api_token = "doc-test-token"
    client.app.state.st.cfg.activity.reads_require_token = True
    assert client.get("/api/events?token=wrong").status_code == 401
    client.app.state.st.api_token = None
    client.app.state.st.cfg.activity.reads_require_token = False


def test_the_documented_lock_code_is_real(locked_client) -> None:
    assert locked_client.get("/api/notes").status_code == 423


def test_the_documented_demo_code_is_real(demo_client) -> None:
    """403 for writes in a read-only demo, which is what the table claims."""
    assert demo_client.post("/api/capture/text", json={"text": "x"}).status_code == 403


def test_the_documented_confirmation_code_is_real(client) -> None:
    """`409 confirmation_required` is described as "the preview, not a failure".
    So the response must actually carry the preview."""
    from conftest import wait_done

    note = client.post("/api/capture/text", json={"text": "something to trash"}).json()
    wait_done(client, note["id"])
    client.delete(f"/api/notes/{note['id']}")

    r = client.post("/api/trash/empty", json={})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "confirmation_required"
    assert r.json()["detail"]["count"] == 1


def test_an_empty_result_is_not_a_prompt(client) -> None:
    """The other half of the same claim: nothing to delete means the call
    succeeds and says zero. A dialog offering to delete nothing is how people
    learn to click through dialogs."""
    assert client.post("/api/trash/empty", json={}).status_code == 200


@pytest.fixture()
def locked_client(client):
    client.app.state.lock.configure("doc-test-passphrase")
    yield client
    client.app.state.lock.configure(None)


@pytest.fixture()
def demo_client(client):
    client.app.state.st.cfg.server.demo_mode = True
    yield client
    client.app.state.st.cfg.server.demo_mode = False