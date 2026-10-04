"""Config round-trip safety.

Three real defects these guard against, all of which silently lose data:
  1. `_coerce` never fires (dataclasses report annotation *strings* under
     `from __future__ import annotations`), so a hand-edited `port = "seven"`
     reaches uvicorn as a str.
  2. `save_config` escapes only `\\` and `"`, so a value containing a newline
     emits TOML that fails to parse.
  3. A parse failure returns *all defaults*, so one bad byte wipes every
     setting — and the next PUT rewrites the file from defaults.
"""

from __future__ import annotations

import pytest

import fleeting.config as fcfg
from fleeting.config import Config, load_config, save_config


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """Point save/load_config at a throwaway path; also redirect CONFIG_DIR."""
    path = tmp_path / "config.toml"
    monkeypatch.setattr(fcfg, "CONFIG_PATH", path)
    monkeypatch.setattr(fcfg, "CONFIG_DIR", tmp_path)
    return path


# ---------------------------------------------------------------------------
# 1. type coercion
# ---------------------------------------------------------------------------


def test_int_field_coerced_from_string(cfg_file) -> None:
    cfg_file.write_text('[server]\nport = "8080"\n', encoding="utf-8")
    cfg = load_config()
    assert cfg.server.port == 8080
    assert isinstance(cfg.server.port, int)


def test_unparseable_int_falls_back_to_default(cfg_file) -> None:
    cfg_file.write_text('[server]\nport = "seven"\n', encoding="utf-8")
    cfg = load_config()
    assert cfg.server.port == 7425
    assert isinstance(cfg.server.port, int)


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("false", False), ("1", True), ("0", False), ("yes", True), ("on", True)],
)
def test_bool_field_coerced_from_string(cfg_file, raw: str, expected: bool) -> None:
    cfg_file.write_text(f"[paths]\nvault_sync = '{raw}'\n", encoding="utf-8")
    cfg = load_config()
    assert cfg.paths.vault_sync is expected


def test_bool_field_preserved_when_already_bool(cfg_file) -> None:
    cfg_file.write_text("[paths]\nvault_sync = false\n", encoding="utf-8")
    assert load_config().paths.vault_sync is False


# ---------------------------------------------------------------------------
# 2. values that would otherwise emit invalid TOML
# ---------------------------------------------------------------------------


def test_newline_in_value_round_trips(cfg_file) -> None:
    cfg = Config()
    cfg.paths.vault_dir = "/tmp/vault\n[activity]\nenabled = false"
    save_config(cfg)
    assert load_config().paths.vault_dir == "/tmp/vault\n[activity]\nenabled = false"


def test_quotes_and_backslashes_round_trip(cfg_file) -> None:
    cfg = Config()
    cfg.llm.base_url = 'http://h/a"b\\c'
    save_config(cfg)
    assert load_config().llm.base_url == 'http://h/a"b\\c'


def test_carriage_return_and_tab_round_trip(cfg_file) -> None:
    cfg = Config()
    cfg.activity.watch_dirs = "~/a\rb\tc"
    save_config(cfg)
    assert load_config().activity.watch_dirs == "~/a\rb\tc"


def test_full_config_round_trips_all_sections(cfg_file) -> None:
    cfg = Config()
    cfg.server.port = 9000
    cfg.paths.vault_sync = False
    cfg.llm.model = "qwen3:8b"
    cfg.llm.timeout_secs = 30
    cfg.transcribe.model = "small"
    cfg.youtube.max_duration_min = 10
    cfg.notifications.desktop = False
    cfg.activity.poll_secs = 45
    cfg.activity.idle_after_min = 9

    save_config(cfg)
    loaded = load_config()

    assert loaded.server.port == 9000
    assert loaded.paths.vault_sync is False
    assert loaded.llm.model == "qwen3:8b"
    assert loaded.llm.timeout_secs == 30
    assert loaded.transcribe.model == "small"
    assert loaded.youtube.max_duration_min == 10
    assert loaded.notifications.desktop is False
    assert loaded.activity.poll_secs == 45
    assert loaded.activity.idle_after_min == 9


# ---------------------------------------------------------------------------
# 3. a corrupt file must not silently reset every setting
# ---------------------------------------------------------------------------


def test_corrupt_file_does_not_wipe_settings(cfg_file) -> None:
    """A bad byte must not become "user has no settings" — the file is the truth.

    If the file exists we cannot parse, the only non-destructive option is to
    return defaults *without* writing; the next successful parse restores it.
    """
    cfg = Config()
    cfg.server.port = 9999
    cfg.llm.model = "keep-me"
    save_config(cfg)
    broken = '[server\nport = broken\n'
    cfg_file.write_text(broken, encoding="utf-8")

    load_config()  # must not overwrite

    assert cfg_file.read_text(encoding="utf-8") == broken
    # And once the user fixes it, their settings are still there.
    cfg_file.write_text('[server]\nport = 9999\n\n[llm]\nmodel = "keep-me"\n', encoding="utf-8")
    loaded = load_config()
    assert loaded.server.port == 9999
    assert loaded.llm.model == "keep-me"


def test_recoverable_corruption_keeps_readable_sections(cfg_file) -> None:
    """One bad value in one section must not discard the other sections."""
    cfg_file.write_text(
        '[server]\nport = "seven"\n\n[llm]\nmodel = "keep-me"\ntimeout_secs = 45\n',
        encoding="utf-8",
    )
    loaded = load_config()
    assert loaded.server.port == 7425  # bad value -> default
    assert loaded.llm.model == "keep-me"  # good section survives
    assert loaded.llm.timeout_secs == 45


def test_corrupt_file_is_preserved_for_inspection(cfg_file) -> None:
    """Never silently overwrite a file we could not parse."""
    bad = '[server\nport = broken\n'
    cfg_file.write_text(bad, encoding="utf-8")
    load_config()
    assert cfg_file.read_text(encoding="utf-8") == bad


def test_save_is_atomic_and_leaves_no_partial_file(cfg_file, monkeypatch) -> None:
    """A crash mid-write must not truncate the live config."""
    cfg = Config()
    cfg.llm.model = "original"
    save_config(cfg)

    def exploding_write(self, *a, **kw):
        raise OSError("disk full")

    # Patch only the tmp-file write; os.replace must stay intact so we can
    # observe that the live file was never touched. monkeypatch.context() keeps
    # the patch scoped, unlike .undo() which would also drop the fixture's
    # CONFIG_PATH redirection and read the real user config.
    with monkeypatch.context() as m:
        m.setattr(fcfg.Path, "write_text", exploding_write)
        with pytest.raises(OSError):
            save_config(cfg)

    assert load_config().llm.model == "original"
    assert not list(cfg_file.parent.glob("*.tmp")), "temp file left behind"


# ---------------------------------------------------------------------------
# unknown keys / comments must survive a settings write
# ---------------------------------------------------------------------------


def test_unknown_keys_are_preserved(cfg_file) -> None:
    """A hand-added key must survive a settings save.

    Comments are NOT preserved (the file is regenerated) — losing a comment is
    cosmetic, losing a key the user deliberately added is not.
    """
    cfg_file.write_text(
        '[server]\nport = 1234\nfuture_key = "keep"\n\n[llm]\nextras = [1, 2]\n',
        encoding="utf-8",
    )
    save_config(load_config())
    text = cfg_file.read_text(encoding="utf-8")
    assert 'future_key = "keep"' in text
    assert "extras = [1, 2]" in text
    assert "port = 1234" in text
    # ...and the preserved keys must still parse back.
    assert load_config().server.port == 1234