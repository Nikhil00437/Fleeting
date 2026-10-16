"""#119 and the ingest queue.

Four properties, ordered by how badly each hurts when it is wrong:

1. **Re-running does not duplicate.** Every other property is decoration next to
   this one. "Import my notes folder again" is a thing people do precisely
   because they are not sure the first run worked, and an importer that
   duplicates a year of notes is worse than no importer.
2. **Imported notes join the existing pipeline**, as `status=pending`. That *is*
   the "run through enrichment and embeddings" requirement — the import does not
   call a model, it queues like every other capture, so 2,000 files do not block.
3. **One bad file does not abandon the rest.** Its failure is counted and named;
   the other 1,999 still import.
4. **Importing your own vault is refused by default**, because that duplicates
   every note the mirror already has — the single most likely way somebody hurts
   themselves with this button.

Plus the job-level guarantees: a failing job is recorded rather than raised (a
raise leaves the row `running` forever, indistinguishable from "still working"),
and progress counts *finished* jobs — failed ones included — so the bar reaches
100% on a folder with one bad file in it.
"""

from __future__ import annotations

import pytest

from fleeting.services import ingest, ingest_markdown


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "i.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


@pytest.fixture()
def folder(tmp_path):
    root = tmp_path / "mynotes"
    (root / "sub").mkdir(parents=True)
    (root / "one.md").write_text(
        "---\ntype: text\ncreated: 2025-03-01T10:00:00+00:00\ntags:\n  - work\n---\n\n"
        "# First note\n\nSomething I wrote.\n",
        encoding="utf-8",
    )
    (root / "sub" / "two.md").write_text("# Second note\n\n- [ ] a task from the list\n", encoding="utf-8")
    return root


def run_import(db, cfg, folder, **kw):
    job = ingest.enqueue(db, ingest_markdown.KIND, str(folder))
    return ingest.run_one(db, cfg, job["id"], **kw)


# ---- the queue -------------------------------------------------------------


def test_a_job_is_queued(db) -> None:
    job = ingest.enqueue(db, "markdown-folder", "/tmp/notes")
    assert job["status"] == ingest.PENDING
    assert ingest.get_job(db, job["id"])["source"] == "/tmp/notes"


def test_jobs_are_listed_newest_first(db) -> None:
    ingest.enqueue(db, "markdown-folder", "/a")
    ingest.enqueue(db, "markdown-folder", "/b")
    assert [j["source"] for j in ingest.list_jobs(db)][:2] == ["/b", "/a"]


def test_an_unknown_job_is_a_lookup_error(db) -> None:
    with pytest.raises(LookupError):
        ingest.run_one(db, None, "nope")


def test_a_job_with_no_parser_fails_rather_than_hanging(db) -> None:
    """A `running` row nobody will ever finish is indistinguishable from work in
    progress."""
    job = ingest.enqueue(db, "no-such-kind", "/tmp/x")
    done = ingest.run_one(db, None, job["id"])
    assert done["status"] == ingest.FAILED
    assert "no parser" in done["error"]


def test_a_raising_parser_is_recorded_not_propagated(db, cfg) -> None:
    def boom(_db, _cfg, _job):
        raise RuntimeError("disk on fire")

    ingest.PARSERS["explodes"] = boom
    try:
        job = ingest.enqueue(db, "explodes", "/tmp/x")
        done = ingest.run_one(db, cfg, job["id"])
        assert done["status"] == ingest.FAILED
        assert "disk on fire" in done["error"]
    finally:
        ingest.PARSERS.pop("explodes", None)


def test_progress_counts_finished_including_failures(db, cfg) -> None:
    """A bar that never reaches 100% because one file was unreadable is worse
    than no bar."""
    ingest.enqueue(db, "markdown-folder", str(folder_of(db)))
    ingest.enqueue(db, "markdown-folder", "/nope-not-there")
    ingest.run_pending(db, cfg)
    progress = ingest.progress(db)
    assert progress["progress"] == 1.0, "a failure is finished, not outstanding"
    assert progress["counts"][ingest.FAILED] == 1
    assert progress["counts"][ingest.DONE] == 1


def folder_of(db) -> "object":
    """A real, empty directory — so the second job's failure is the only one."""
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())


def test_an_empty_queue_is_complete_not_stuck(db) -> None:
    assert ingest.progress(db)["progress"] == 1.0


def test_failures_are_listed_with_their_reason(db, cfg) -> None:
    ingest.enqueue(db, "markdown-folder", "/definitely/not/here")
    ingest.run_pending(db, cfg)
    assert ingest.failures(db)[0]["error"]


# ---- importing a folder ---------------------------------------------------


def test_files_are_imported(db, cfg, folder) -> None:
    job = run_import(db, cfg, folder)
    assert job["status"] == ingest.DONE
    assert job["detail"]["imported"] == 2


def test_the_title_comes_from_the_heading(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    assert {n["title"] for n in db.list_notes(limit=10)} == {"First note", "Second note"}


def test_tags_are_imported(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    tagged = [n for n in db.list_notes(limit=10) if n["title"] == "First note"][0]
    assert tagged["tags"] == ["work"]


def test_checklist_items_become_action_items(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    rows = [dict(r) for r in db.execute("SELECT * FROM tasks")]
    titles = {r.get("title") or r.get("text") for r in rows}
    assert "a task from the list" in titles


def test_the_created_date_is_preserved(db, cfg, folder) -> None:
    """An import that resets every timestamp makes the timeline useless."""
    run_import(db, cfg, folder)
    note = [n for n in db.list_notes(limit=10) if n["title"] == "First note"][0]
    assert note["created_at"].startswith("2025-03-01")


def test_imported_notes_join_the_pipeline_as_pending(db, cfg, folder) -> None:
    """That *is* the "run through enrichment and embeddings" requirement."""
    run_import(db, cfg, folder)
    assert all(n["status"] == "pending" for n in db.list_notes(limit=10))


def test_imported_notes_are_marked_generated(db, cfg, folder) -> None:
    """The app wrote them, not the user — every text heuristic that reads a note
    is wrong on LLM-shaped prose."""
    run_import(db, cfg, folder)
    assert all(n["generated"] == 1 for n in db.list_notes(limit=10))


def test_the_source_says_where_it_came_from(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    note = db.list_notes(limit=10)[0]
    assert note["source"]["imported_from"] == "markdown-folder"


def test_nested_folders_are_walked(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    assert "Second note" in {n["title"] for n in db.list_notes(limit=10)}


def test_noise_folders_are_skipped(db, cfg, folder) -> None:
    (folder / ".obsidian").mkdir()
    (folder / ".obsidian" / "workspace.md").write_text("---\nid: w\n---\n", encoding="utf-8")
    run_import(db, cfg, folder)
    assert not any("workspace" in n["title"] for n in db.list_notes(limit=10))


# ---- idempotence -----------------------------------------------------------


def test_importing_twice_adds_nothing(db, cfg, folder) -> None:
    """An importer that duplicates a year of notes is worse than no importer."""
    run_import(db, cfg, folder)
    second = run_import(db, cfg, folder)
    assert second["detail"]["imported"] == 0
    assert len(db.list_notes(limit=50)) == 2


def test_the_second_run_reports_what_it_skipped(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    assert run_import(db, cfg, folder)["detail"]["skipped"] == 2


def test_a_new_file_in_an_imported_folder_is_still_picked_up(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    (folder / "three.md").write_text("# Third\n", encoding="utf-8")
    assert run_import(db, cfg, folder)["detail"]["imported"] == 1


def test_forgetting_a_source_allows_a_re_import(db, cfg, folder) -> None:
    """Otherwise a partial import is unretryable forever."""
    run_import(db, cfg, folder)
    ingest.forget_source(db, f"file://{(folder / 'one.md').resolve()}", ingest_markdown.KIND)
    assert run_import(db, cfg, folder)["detail"]["imported"] == 1


def test_the_same_path_under_a_different_kind_is_not_a_duplicate(db, cfg, folder) -> None:
    ingest.mark_ingested(db, f"file://{(folder / 'one.md').resolve()}", "rss")
    assert not ingest.already_ingested(db, f"file://{(folder / 'one.md').resolve()}", "markdown-folder")


# ---- partial failure -------------------------------------------------------


def test_one_bad_file_does_not_abandon_the_rest(db, cfg, folder) -> None:
    """With an actually-unreadable file present.

    The first version of this test used a folder of *good* files and asserted
    `failed_count == 0`, which never entered the except branch at all — so
    mutation checking found the branch untested. A directory named `*.md` is
    unreadable without needing permissions games that behave differently for
    root.
    """
    # A dangling symlink: `_files` classifies it as a file (not a directory) and
    # `read_text` then raises. A *directory* named `broken.md` would be recursed
    # into instead, and chmod games behave differently for root.
    (folder / "broken.md").symlink_to(folder / "does-not-exist.md")
    job = run_import(db, cfg, folder)
    assert job["detail"]["imported"] == 2, "the readable files still imported"
    assert job["detail"]["failed_count"] == 1
    assert job["detail"]["failed"][0]["file"] == "broken.md"


def test_a_failure_is_named_so_the_user_can_find_it(db, cfg, folder) -> None:
    (folder / "broken.md").symlink_to(folder / "does-not-exist.md")
    job = run_import(db, cfg, folder)
    assert job["detail"]["failed"][0]["error"]


def test_a_partly_failed_job_still_counts_as_done(db, cfg, folder) -> None:
    """A folder with one bad file in it is an import, not a failure."""
    (folder / "broken.md").symlink_to(folder / "does-not-exist.md")
    assert run_import(db, cfg, folder)["status"] == ingest.DONE


def test_a_missing_source_fails_clearly(db, cfg) -> None:
    job = run_import(db, cfg, "/definitely/not/here")
    assert job["status"] == ingest.FAILED
    assert "not a directory" in job["error"]


def test_importing_the_vault_is_refused(db, cfg) -> None:
    """Duplicating every note the mirror already has is the single most likely
    way somebody hurts themselves with this button."""
    job = run_import(db, cfg, cfg.vault_dir)
    assert job["status"] == ingest.FAILED
    assert "vault directory" in job["error"]


def test_importing_the_vault_can_be_forced(db, cfg) -> None:
    cfg.ingest_allow_vault = True
    import pathlib

    pathlib.Path(cfg.vault_dir).mkdir(parents=True, exist_ok=True)
    job = run_import(db, cfg, cfg.vault_dir)
    assert job["status"] == ingest.DONE


# ---- preview ---------------------------------------------------------------


def test_the_preview_says_what_would_happen(db, cfg, folder) -> None:
    detail = ingest_markdown.preview(db, cfg, str(folder))
    assert detail["would_import"] == 2
    assert detail["already_imported"] == 0


def test_the_preview_counts_what_is_already_there(db, cfg, folder) -> None:
    run_import(db, cfg, folder)
    detail = ingest_markdown.preview(db, cfg, str(folder))
    assert detail["would_import"] == 0
    assert detail["already_imported"] == 2


def test_the_preview_writes_nothing(db, cfg, folder) -> None:
    ingest_markdown.preview(db, cfg, str(folder))
    assert db.list_notes(limit=10) == []


def test_the_preview_of_a_missing_folder_says_so(db, cfg) -> None:
    assert ingest_markdown.preview(db, cfg, "/nope")["exists"] is False


# ---- the endpoints ---------------------------------------------------------


def test_the_preview_endpoint(client, cfg, folder) -> None:
    body = client.post("/api/ingest/preview", json={"kind": "markdown-folder", "source": str(folder)}).json()
    assert body["would_import"] == 2


def test_the_queue_endpoint(client, cfg, folder) -> None:
    r = client.post("/api/ingest", json={"kind": "markdown-folder", "source": str(folder)})
    assert r.status_code == 200, r.text
    assert client.get("/api/ingest/jobs").json()["jobs"]


def test_running_a_job_through_the_api(client, cfg, folder) -> None:
    job = client.post("/api/ingest", json={"kind": "markdown-folder", "source": str(folder)}).json()
    r = client.post(f"/api/ingest/jobs/{job['id']}/run")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert len(client.app.state.st.db.list_notes(limit=10)) == 2


def test_progress_through_the_api(client, cfg, folder) -> None:
    job = client.post("/api/ingest", json={"kind": "markdown-folder", "source": str(folder)}).json()
    client.post(f"/api/ingest/jobs/{job['id']}/run")
    assert client.get("/api/ingest/progress").json()["progress"] == 1.0