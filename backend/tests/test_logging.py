"""#389: log level, log format, and a log that stops growing forever.

Two things motivated this beyond the item's wording.

**The log had no bound.** `logging.FileHandler` appends forever, and the
user's log had reached 6.2 MB / 41,796 lines with no rotation — on a local app
that is a slow disk leak nobody asked for.

**The level was hardcoded to INFO.** There was no way to turn a chatty module
down without editing source, which is the opposite of what a log level is for.

On JSON: nothing in the codebase parses the log — `grep` finds exactly one
consumer and it is the writer. So `json` is opt-in rather than the default,
because a local user tailing their own log wants to read it. It exists for
`#395`'s diagnostics bundle, which has to filter errors out of a log rather
than grep a prose line.
"""

from __future__ import annotations

import json
import logging
import logging.handlers


from fleeting.config import LoggingConfig, load_config, save_config


def _records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("fleeting")]


# ---- the level ------------------------------------------------------------


def test_level_is_read_from_config(tmp_path, monkeypatch) -> None:
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "CONFIG_PATH", tmp_path / "config.toml")
    (tmp_path / "config.toml").write_text('[logging]\nlevel = "DEBUG"\n')
    cfg = load_config()
    assert cfg.logging.level == "DEBUG"


def test_an_unknown_level_falls_back_to_info(tmp_path, monkeypatch) -> None:
    """A typo must not leave the app unable to log at all.

    Normalised where it is *used*, not in the loader: rewriting the stored
    value would silently edit the user's config on the next save, so a typo
    would disappear instead of being visible and fixable.
    """
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "LOG_PATH", tmp_path / "l.log")
    cfg = LoggingConfig(level="LOUD")
    main_mod._setup_logging(cfg)
    try:
        assert logging.getLogger().level == logging.INFO
        # The typo survives in config so the Settings view can show it.
        assert cfg.level == "LOUD"
    finally:
        logging.getLogger().handlers.clear()


def test_the_level_reaches_the_root_logger(tmp_path, monkeypatch) -> None:
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "LOG_PATH", tmp_path / "l.log")
    cfg = LoggingConfig(level="WARNING")
    main_mod._setup_logging(cfg)
    try:
        root = logging.getLogger()
        assert root.level == logging.WARNING
    finally:
        logging.getLogger().handlers.clear()


def test_quiet_suppresses_info_but_keeps_errors(tmp_path, monkeypatch) -> None:
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    monkeypatch.setattr(fcfg, "LOG_PATH", tmp_path / "l.log")
    main_mod._setup_logging(LoggingConfig(level="ERROR"))
    log = logging.getLogger("fleeting.test")
    try:
        assert not log.isEnabledFor(logging.INFO)
        assert log.isEnabledFor(logging.ERROR)
    finally:
        logging.getLogger().handlers.clear()


# ---- the format -----------------------------------------------------------


def test_text_is_the_default_so_a_local_user_can_read_their_log() -> None:
    assert LoggingConfig().log_format == "text"


def test_json_lines_carry_the_fields_a_bundle_needs(tmp_path, monkeypatch) -> None:
    """One object per line, with the fields `#395` would filter on."""
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    log_file = tmp_path / "l.log"
    monkeypatch.setattr(fcfg, "LOG_PATH", log_file)
    main_mod._setup_logging(LoggingConfig(log_format="json", level="DEBUG"))
    logging.getLogger("fleeting.x").warning("something went wrong", extra={"note_id": "n-1"})
    try:
        lines = [ln for ln in log_file.read_text().splitlines() if ln.strip()]
        assert lines, "nothing was written"
        rec = json.loads(lines[-1])
        assert rec["level"] == "WARNING"
        assert rec["logger"] == "fleeting.x"
        assert rec["message"] == "something went wrong"
        assert rec["note_id"] == "n-1", "extras must survive into the record"
        assert rec["timestamp"], "a log line with no time cannot be correlated"
    finally:
        logging.getLogger().handlers.clear()


def test_json_survives_an_unserialisable_extra(tmp_path, monkeypatch) -> None:
    """A stray object in `extra` must not cost you the whole log line."""
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    log_file = tmp_path / "l.log"
    monkeypatch.setattr(fcfg, "LOG_PATH", log_file)
    main_mod._setup_logging(LoggingConfig(log_format="json"))
    logging.getLogger("fleeting.x").warning("boom", extra={"thing": object()})
    try:
        rec = json.loads(log_file.read_text().splitlines()[-1])
        assert rec["message"] == "boom"
    finally:
        logging.getLogger().handlers.clear()


# ---- rotation -------------------------------------------------------------


def test_the_log_is_bounded(tmp_path, monkeypatch) -> None:
    """The user's log reached 6.2 MB before this existed."""
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    log_file = tmp_path / "l.log"
    monkeypatch.setattr(fcfg, "LOG_PATH", log_file)
    main_mod._setup_logging(LoggingConfig(max_bytes=2048, backups=2))
    log = logging.getLogger("fleeting.noisy")
    try:
        for i in range(400):
            log.info("line %d %s", i, "x" * 80)
        assert log_file.stat().st_size <= 4096, "the live file grew past its cap"
        backups = sorted(tmp_path.glob("l.log.*"))
        assert backups, "no rotated file was written"
        assert len(backups) <= 2, f"kept {len(backups)} backups"
    finally:
        logging.getLogger().handlers.clear()


def test_json_includes_the_traceback(tmp_path, monkeypatch) -> None:
    """The first version of the formatter referenced `self.formatException`
    from a plain nested function, where `self` does not exist — so every record
    carrying a traceback raised NameError while being logged. `ruff`'s F821
    caught it; this pins the behaviour it was meant to produce.
    """
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    log_file = tmp_path / "l.log"
    monkeypatch.setattr(fcfg, "LOG_PATH", log_file)
    main_mod._setup_logging(LoggingConfig(log_format="json"))
    try:
        try:
            raise ValueError("kaboom")
        except ValueError:
            logging.getLogger("fleeting.x").exception("while doing a thing")
        rec = json.loads(log_file.read_text().splitlines()[-1])
        assert "kaboom" in rec["exception"]
        assert rec["message"] == "while doing a thing"
    finally:
        logging.getLogger().handlers.clear()


def test_rotation_can_be_switched_off(tmp_path, monkeypatch) -> None:
    from fleeting import main as main_mod
    from fleeting import config as fcfg

    log_file = tmp_path / "l.log"
    monkeypatch.setattr(fcfg, "LOG_PATH", log_file)
    main_mod._setup_logging(LoggingConfig(max_bytes=0))
    log = logging.getLogger("fleeting.noisy")
    try:
        for i in range(300):
            log.info("line %d", i)
        assert not list(tmp_path.glob("l.log.*")), "rotated despite being off"
    finally:
        logging.getLogger().handlers.clear()


# ---- round trip -----------------------------------------------------------


def test_the_setting_survives_a_save(tmp_path, monkeypatch) -> None:
    """config.toml is hand-editable, so a settings save must not eat it.

    Pins unknown-key preservation, which works. It deliberately does **not**
    assert comment preservation: `save_config` regenerates the file from
    `_SECTIONS` and drops every comment, even though its docstring and
    AGENTS.md both claim comments are preserved. That is a real bug, in
    `save_config` rather than here — tracked separately rather than fixed in a
    logging change, because a mistake in that function loses user settings.
    """
    from fleeting import config as fcfg

    path = tmp_path / "config.toml"
    monkeypatch.setattr(fcfg, "CONFIG_PATH", path)
    path.write_text(
        '[logging]\nlevel = "WARNING"\nmy_custom = 7\n\n[activity]\n# why this is off\nenabled = false\n'
    )
    cfg = load_config()
    cfg.logging.level = "DEBUG"
    cfg.logging.log_format = "json"
    save_config(cfg)

    again = load_config()
    assert again.logging.level == "DEBUG"
    assert again.logging.log_format == "json"
    assert "my_custom" in path.read_text(), "a hand-added key was dropped"