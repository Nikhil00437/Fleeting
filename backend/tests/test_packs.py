"""#495: an offline-friendly theme and prompt pack format.

"Offline-friendly" is the whole requirement and it is a threat model, not a
feature: a pack is a file someone drops into a folder, from a USB stick, from a
friend, from a directory of 400 half-finished experiments. A malformed one must
cost you that one pack, never the app — so every parser path here returns a
reason instead of raising, and there is a test for each reason.

The second threat is a pack that is valid JSON and still wrong: a theme key that
is not a CSS custom property, a token value that would rewrite `--ink-100` into
something unreadable. `_token_name` is the gate, and it is tested directly
because it is the only thing between a downloaded file and your entire UI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleeting.config import Config
from fleeting.services.packs import install_pack, list_packs, load_packs


def write_pack(d: Path, filename: str, payload: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(payload), encoding="utf-8")


def full_pack(**over) -> dict:
    base = {
        "name": "Zettel",
        "description": "Atomic notes",
        "version": 1,
        "theme": {"--ink-100": "#f0f0f0", "--ember-400": "#ff5500"},
        "prompts": {"style_guide": "One idea per note.", "preferred_tags": "inbox, idea"},
    }
    base.update(over)
    return base


@pytest.fixture()
def sandbox(tmp_path, monkeypatch) -> Path:
    import fleeting.config as fcfg

    d = tmp_path / "packs"
    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    return d


# ---- discovery ------------------------------------------------------------


def test_a_folder_with_no_packs_is_empty_not_an_error(sandbox: Path) -> None:
    """First run has no folder at all. That is the common case, not an error."""
    assert list_packs(sandbox, Config()) == []


def test_a_pack_is_listed(sandbox: Path) -> None:
    write_pack(sandbox, "zettel.json", full_pack())
    packs = list_packs(sandbox, Config())
    assert [p["name"] for p in packs] == ["Zettel"]
    assert packs[0]["theme"]["--ember-400"] == "#ff5500"


def test_a_directory_of_packs_is_sorted_by_name(sandbox: Path) -> None:
    write_pack(sandbox, "b.json", full_pack(name="Beta"))
    write_pack(sandbox, "a.json", full_pack(name="Alpha"))
    assert [p["name"] for p in list_packs(sandbox, Config())] == ["Alpha", "Beta"]


def test_the_active_pack_is_flagged(sandbox: Path) -> None:
    write_pack(sandbox, "z.json", full_pack(name="Zettel"))
    cfg = Config()
    cfg.theme.active = "Zettel"
    assert list_packs(sandbox, cfg)[0]["active"] is True


def test_the_active_pack_is_flagged_by_filename_when_it_has_no_name(sandbox: Path) -> None:
    """A hand-written pack may omit `name`. Matching on the filename means it is
    still installable instead of being invisible until someone adds a key."""
    write_pack(sandbox, "Solar.json", {"theme": {"--ink-100": "#fff"}})
    cfg = Config()
    cfg.theme.active = "Solar"
    assert list_packs(sandbox, cfg)[0]["active"] is True


# ---- containing a bad pack ------------------------------------------------


def test_a_malformed_file_is_skipped_with_a_reason(sandbox: Path) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "broken.json").write_text("{not json", encoding="utf-8")
    write_pack(sandbox, "good.json", full_pack())
    packs, errors = load_packs(sandbox, Config())
    assert [p["name"] for p in packs] == ["Zettel"]
    assert len(errors) == 1
    assert "broken.json" in errors[0]


def test_a_pack_that_is_not_an_object_is_skipped(sandbox: Path) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "list.json").write_text("[1, 2, 3]", encoding="utf-8")
    packs, errors = load_packs(sandbox, Config())
    assert packs == []
    assert errors


def test_a_theme_key_that_is_not_a_custom_property_is_dropped(sandbox: Path) -> None:
    """The only gate between a downloaded file and your whole UI."""
    write_pack(sandbox, "x.json", full_pack(theme={"color": "red", "--ink-100": "#fff"}))
    pack = list_packs(sandbox, Config())[0]
    assert pack["theme"] == {"--ink-100": "#fff"}


def test_a_token_value_that_is_not_a_css_value_is_dropped(sandbox: Path) -> None:
    """A token that breaks the stylesheet breaks every component that reads it."""
    write_pack(sandbox, "x.json", full_pack(theme={"--ink-100": "red; } body { display: none", "--ember-400": "#f60"}))
    pack = list_packs(sandbox, Config())[0]
    assert pack["theme"] == {"--ember-400": "#f60"}


def test_a_theme_that_is_not_a_dict_is_ignored(sandbox: Path) -> None:
    write_pack(sandbox, "x.json", full_pack(theme="dark"))
    assert list_packs(sandbox, Config())[0]["theme"] == {}


def test_prompts_that_are_not_strings_are_ignored(sandbox: Path) -> None:
    write_pack(sandbox, "x.json", full_pack(prompts={"style_guide": 42, "preferred_tags": "ok"}))
    assert list_packs(sandbox, Config())[0]["prompts"] == {"preferred_tags": "ok"}


def test_an_unknown_prompt_key_is_ignored(sandbox: Path) -> None:
    """Only keys that map to real settings are applied. A pack that can set
    arbitrary config fields is a pack that can point your vault at /etc."""
    write_pack(sandbox, "x.json", full_pack(prompts={"vault_dir": "/etc/passwd"}))
    assert list_packs(sandbox, Config())[0]["prompts"] == {}


def test_one_bad_pack_does_not_hide_the_others(sandbox: Path) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "a.json").write_text("{", encoding="utf-8")
    (sandbox / "b.json").write_text("{ broken", encoding="utf-8")
    (sandbox / "c.json").write_text(json.dumps(full_pack()))
    packs, errors = load_packs(sandbox, Config())
    assert len(packs) == 1
    assert len(errors) == 2


# ---- installing -----------------------------------------------------------


def test_installing_applies_the_theme_and_the_prompts(sandbox: Path) -> None:
    write_pack(sandbox, "z.json", full_pack())
    cfg = Config()
    install_pack(sandbox, "Zettel", cfg, save=lambda _c: None)
    assert cfg.theme.active == "Zettel"
    assert cfg.writing.style_guide == "One idea per note."
    assert cfg.llm.preferred_tags == "inbox, idea"


def test_installing_an_empty_prompt_does_not_wipe_your_settings(sandbox: Path) -> None:
    """A theme pack must not blank a style guide you spent time writing."""
    write_pack(sandbox, "z.json", full_pack(prompts={}))
    cfg = Config()
    cfg.writing.style_guide = "mine"
    install_pack(sandbox, "Zettel", cfg, save=lambda _c: None)
    assert cfg.writing.style_guide == "mine"


def test_installing_saves_the_config(sandbox: Path) -> None:
    """Without this the install only lasts until the next restart."""
    write_pack(sandbox, "z.json", full_pack())
    saved: list[Config] = []
    install_pack(sandbox, "Zettel", Config(), save=saved.append)
    assert len(saved) == 1


def test_installing_an_unknown_pack_raises(sandbox: Path) -> None:
    with pytest.raises(KeyError):
        install_pack(sandbox, "Nope", Config(), save=lambda _c: None)


def test_the_file_stem_wins_when_a_pack_has_no_name(sandbox: Path) -> None:
    """So the `active` flag can be set from the list without a name field."""
    write_pack(sandbox, "Solar.json", {"theme": {"--ink-100": "#fff"}})
    # The listed name matters too: a pack showing as blank in the list is one
    # nobody clicks, and install-by-stem working while the list shows "" is the
    # state where both halves disagree.
    assert list_packs(sandbox, Config())[0]["name"] == "Solar"
    cfg = Config()
    install_pack(sandbox, "Solar", cfg, save=lambda _c: None)
    assert cfg.theme.active == "Solar"


def test_a_pack_with_a_name_displays_its_description(sandbox: Path) -> None:
    write_pack(sandbox, "z.json", full_pack(description="Atomic notes"))
    assert list_packs(sandbox, Config())[0]["description"] == "Atomic notes"


def test_list_packs_never_raises_whatever_is_in_the_folder(sandbox: Path) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "a.json").write_text("null", encoding="utf-8")
    (sandbox / "b.json").write_text('{"name": 5}', encoding="utf-8")
    (sandbox / "c.md").write_text("not a pack", encoding="utf-8")
    assert isinstance(list_packs(sandbox, Config()), list)

# ---- over the API ---------------------------------------------------------


def test_the_endpoint_lists_packs(client, tmp_path) -> None:
    d = tmp_path / "packs"
    write_pack(d, "z.json", full_pack())
    body = client.get("/api/packs", params={"dir": str(d)}).json()
    assert [p["name"] for p in body["packs"]] == ["Zettel"]
    assert body["packs"][0]["active"] is False
    assert body["errors"] == []


def test_the_endpoint_reports_unreadable_packs_rather_than_hiding_them(client, tmp_path) -> None:
    """Silently dropping a pack the user wrote is indistinguishable from it
    never having been found, which sends them looking for the wrong bug."""
    d = tmp_path / "packs"
    d.mkdir(parents=True)
    (d / "oops.json").write_text("{", encoding="utf-8")
    body = client.get("/api/packs", params={"dir": str(d)}).json()
    assert body["packs"] == []
    assert "oops.json" in body["errors"][0]


def test_installing_over_the_api_persists(client, tmp_path) -> None:
    import fleeting.config as fcfg

    d = tmp_path / "packs"
    write_pack(d, "z.json", full_pack())
    out = client.post("/api/packs/Zettel/install", params={"dir": str(d)})
    assert out.status_code == 200
    # Re-read from disk rather than trusting the response body.
    assert fcfg.CONFIG_PATH.exists()
    assert "Zettel" in fcfg.CONFIG_PATH.read_text(encoding="utf-8")


def test_installing_an_unknown_pack_is_a_404(client, tmp_path) -> None:
    r = client.post("/api/packs/Nope/install", params={"dir": str(tmp_path / "packs")})
    assert r.status_code == 404


def test_an_empty_prompt_value_does_not_wipe_your_settings(sandbox: Path) -> None:
    """Absent key and empty string are different inputs and only one was tested.

    A pack author clearing a field is a reasonable thing to write; a theme-only
    pack with `"style_guide": ""` is not meant to blank a guide someone spent
    time on, and there is no way to tell the two apart from the file alone.
    Deleting is something you do in Settings.
    """
    write_pack(sandbox, "z.json", full_pack(prompts={"style_guide": "", "preferred_tags": "  "}))
    cfg = Config()
    cfg.writing.style_guide = "mine"
    cfg.llm.preferred_tags = "mine"
    install_pack(sandbox, "Zettel", cfg, save=lambda _c: None)
    assert cfg.writing.style_guide == "mine"
    assert cfg.llm.preferred_tags == "mine"


@pytest.mark.parametrize(
    "declared,expected",
    [
        ('""', "Blank"),          # a template whose name field got emptied
        ('"   "', "Blank"),       # whitespace is not a name either
        ("5", "Blank"),           # a numeric typo must not become the pack's name
        ("[]", "Blank"),
    ],
)
def test_a_name_that_is_not_a_usable_string_falls_back_to_the_filename(
    sandbox: Path, declared: str, expected: str
) -> None:
    """Every one of these renders as a blank or nonsense row in a list, which is
    the pack nobody clicks. The filename is always there and always sensible."""
    write_pack(sandbox, "Blank.json", {"name": json.loads(declared), "theme": {"--ink-100": "#fff"}})
    assert list_packs(sandbox, Config())[0]["name"] == expected
