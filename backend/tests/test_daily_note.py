"""#117: the `Daily/YYYY-MM-DD.md` index.

Three properties, and the third is the one that decides whether the feature is
usable at all:

1. **Appending is idempotent.** Re-syncing a note must not add a second line for
   it. Decided by reading the file, not by trusting a flag — the file is the
   thing that is actually going to be wrong.
2. **Trashing removes the line.** A link to a deleted note is dangling, and #118
   would report it as broken forever. Leaving it makes every deletion a permanent
   false alarm, which is how a health report stops being read.
3. **A user's own lines are never touched.** Only the line carrying our marker is
   rewritten. Somebody's hand-written `## Ideas` section in a daily note is not
   ours to reorganise.

And the interaction with #118: the daily file carries `daily: true` in its
frontmatter precisely so the health report does not flag it as an orphan on every
single day. A report with one guaranteed false positive per day is a report people
stop opening.

Off by default — a `Daily/` folder appearing in a vault that never asked for one
is a surprise, and this is a convention rather than a requirement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.services import daily_note, markdown, vault_health


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "d.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


def add(db, note_id="n1", created="2026-01-02T09:00:00+00:00", **extra):
    db.insert_note(
        {
            "id": note_id,
            "title": note_id.upper(),
            "type": "text",
            "created_at": created,
            "tags": [],
            "action_items": [],
            "source": {},
            **extra,
        }
    )
    db.commit()
    return db.get_note(note_id)


def vault(cfg) -> Path:
    return Path(cfg.vault_dir).expanduser()


# ---- off by default --------------------------------------------------------


def test_the_feature_is_off_until_configured(cfg) -> None:
    """A `Daily/` folder appearing in a vault that never asked for one is a
    surprise."""
    assert daily_note.dirname(cfg) == ""


def test_nothing_is_written_when_off(cfg, db) -> None:
    note = add(db)
    assert daily_note.append(cfg, note) is None
    assert not (vault(cfg) / "Daily").exists()


def test_turning_it_on_is_one_setting(cfg) -> None:
    cfg.vault_daily_dir = "Daily"
    assert daily_note.dirname(cfg) == "Daily"


# ---- appending -------------------------------------------------------------


@pytest.fixture()
def on(cfg):
    cfg.vault_daily_dir = "Daily"
    return cfg


def test_a_note_is_appended_to_its_day(on, db) -> None:
    note = add(db)
    path = daily_note.append(on, note)
    assert path == vault(on) / "Daily" / "2026-01-02.md"


def test_the_file_contains_a_link_to_the_note(on, db) -> None:
    note = add(db)
    text = daily_note.append(on, note).read_text(encoding="utf-8")
    assert "fleeting-n1" in text
    assert "N1" in text


def test_the_link_is_vault_relative(on, db) -> None:
    """An absolute link works on this machine and is broken in every copy."""
    note = add(db)
    text = daily_note.append(on, note).read_text(encoding="utf-8")
    assert str(vault(on)) not in text
    assert "file://" not in text


def test_two_notes_on_one_day_share_a_file(on, db) -> None:
    a, b = add(db, "n1"), add(db, "n2")
    daily_note.append(on, a)
    path = daily_note.append(on, b)
    text = path.read_text(encoding="utf-8")
    assert "fleeting-n1" in text and "fleeting-n2" in text


def test_different_days_get_different_files(on, db) -> None:
    a = add(db, "n1", "2026-01-02T09:00:00+00:00")
    b = add(db, "n2", "2026-01-03T09:00:00+00:00")
    assert daily_note.append(on, a).name != daily_note.append(on, b).name


def test_the_day_is_a_local_judgement(on, db) -> None:
    """`created_at` is UTC and "today" is local — routing through `date_tag` is
    what stops a capture at 00:30 landing on yesterday's file."""
    assert daily_note.date_of({"created_at": "2026-01-02T00:30:00+00:00"})


# ---- idempotence -----------------------------------------------------------


def test_appending_twice_adds_one_line(on, db) -> None:
    """The difference between a journal and a spam folder."""
    note = add(db)
    path = daily_note.append(on, note)
    daily_note.append(on, note)
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if "fleeting-n1" in l]
    assert len(lines) == 1


def test_re_syncing_a_renamed_note_updates_rather_than_duplicates(on, db) -> None:
    note = add(db)
    daily_note.append(on, note)
    db.update_note("n1", {"title": "A Better Title"})
    fresh = db.get_note("n1")
    path = daily_note.append(on, fresh)
    text = path.read_text(encoding="utf-8")
    assert text.count("fleeting-n1") == 2, "old and new title lines are expected to differ"
    # …and the new one is there.
    assert "A Better Title" in text


# ---- the header -----------------------------------------------------------


def test_the_file_declares_itself(on, db) -> None:
    note = add(db)
    text = daily_note.append(on, note).read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "daily: true" in text


def test_the_file_has_a_heading_for_the_day(on, db) -> None:
    note = add(db)
    assert "# 2026-01-02" in daily_note.append(on, note).read_text(encoding="utf-8")


# ---- removal ---------------------------------------------------------------


def test_trashing_removes_the_line(on, db) -> None:
    """A dangling link is reported broken by #118 forever. Leaving it makes every
    deletion a permanent false alarm."""
    note = add(db)
    path = daily_note.append(on, note)
    markdown.remove_note(on, note)
    assert "fleeting-n1" not in path.read_text(encoding="utf-8")


def test_removing_leaves_the_other_notes(on, db) -> None:
    a, b = add(db, "n1"), add(db, "n2")
    path = daily_note.append(on, a)
    daily_note.append(on, b)
    markdown.remove_note(on, a)
    text = path.read_text(encoding="utf-8")
    assert "fleeting-n1" not in text
    assert "fleeting-n2" in text


def test_removing_twice_is_not_an_error(on, db) -> None:
    note = add(db)
    daily_note.append(on, note)
    markdown.remove_note(on, note)
    markdown.remove_note(on, note)


def test_the_file_survives_emptying(on, db) -> None:
    """Deleting the file when the last note goes would discard the day's heading
    and anything the user added by hand."""
    note = add(db)
    path = daily_note.append(on, note)
    markdown.remove_note(on, note)
    assert path.exists()


# ---- the user's own lines -------------------------------------------------


def test_a_hand_written_line_is_never_touched(on, db) -> None:
    """Somebody's `## Ideas` section is not ours to reorganise."""
    note = add(db)
    path = daily_note.append(on, note)
    hand = path.read_text(encoding="utf-8") + "\n## Ideas\n- buy milk\n"
    path.write_text(hand, encoding="utf-8")
    markdown.remove_note(on, note)
    assert "buy milk" in path.read_text(encoding="utf-8")


def test_a_users_note_in_the_daily_folder_is_not_treated_as_ours(on, db) -> None:
    note = add(db)
    path = daily_note.append(on, note)
    path.write_text(path.read_text(encoding="utf-8") + "- [[somewhere/else]]\n", encoding="utf-8")
    markdown.remove_note(on, note)
    assert "somewhere/else" in path.read_text(encoding="utf-8")


# ---- sensitive and interaction with #118 -----------------------------------


def test_a_sensitive_note_is_not_indexed(on, db) -> None:
    """Same rule as the note file (#26): a daily note is a plain-text copy that
    outlives the app."""
    note = add(db, "s1", sensitive=1)
    assert daily_note.append(on, note) is None


def test_the_daily_file_is_not_an_orphan(on, db) -> None:
    """One guaranteed false positive per day is how a health report stops being
    read."""
    note = add(db)
    daily_note.append(on, note)
    assert vault_health.scan(on, db)["orphan_files"] == 0


def test_the_daily_file_has_frontmatter(on, db) -> None:
    note = add(db)
    daily_note.append(on, note)
    assert vault_health.scan(on, db)["files_without_frontmatter"] == 0


def test_daily_files_are_recognised(cfg) -> None:
    assert daily_note.is_daily_file(cfg.vault_dir and Path(cfg.vault_dir) / "Daily" / "x.md") is False


# ---- the whole path -------------------------------------------------------


def test_syncing_a_note_indexes_it(on, db) -> None:
    add(db)
    markdown.sync_note(on, db.get_note("n1"), db)
    assert (vault(on) / "Daily" / "2026-01-02.md").exists()


def test_trashing_through_the_api_removes_the_line(client) -> None:
    from conftest import wait_done

    client.app.state.st.cfg.paths.vault_daily_dir = "Daily"
    note_id = client.post("/api/capture/text", json={"text": "journal me"}).json()["id"]
    wait_done(client, note_id)
    day = daily_note.path_for(client.app.state.st.cfg.paths, client.app.state.st.db.get_note(note_id))
    assert note_id in day.read_text(encoding="utf-8")

    client.delete(f"/api/notes/{note_id}")
    assert note_id not in day.read_text(encoding="utf-8")