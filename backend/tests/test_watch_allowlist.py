"""#454: an allow-list for file-activity scanning.

The default before this was `"~/Projects, ~/Documents, ~/Downloads"` — three
folders scanned, with metadata gathered and turned into a daily report, without
anyone having asked for it. An allow-list that ships full is not an allow-list.

The properties pinned here, in order of severity:

1. **An empty list scans nothing.** Failing closed is the whole safety property.
2. **A path the allow-list names is the only path read** — across every report
   path, not just the endpoint this started from. There were seven call sites and
   fixing one would have left six able to read a directory the user never named.
3. **Rejections carry a reason.** A directory absent from the preview is
   otherwise indistinguishable from one ignored because of a typo, and "I typed
   it and nothing happened" is the report you cannot act on.
4. **The preview leaks nothing.** Counts per project folder; never a filename.
   A preview that listed filenames would leak the very thing the allow-list
   exists to gate.
5. **Typo-resistant on the dangerous direction.** A missing leading slash turns
   `Projects` into a filesystem-wide scan, so bare and system paths are refused.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path


from fleeting.services.files_activity import (
    NEVER_SCAN,
    preview_allowlist,
    resolve_allowlist,
)


def touch(directory: Path, name: str) -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


# ---- failing closed --------------------------------------------------------


def test_an_empty_allowlist_scans_nothing() -> None:
    """The whole safety property. A default that scans a folder nobody named is
    not a default anyone consented to."""
    assert resolve_allowlist("") == ([], [])


def test_whitespace_only_is_still_empty() -> None:
    assert resolve_allowlist("  ,  ,")[0] == []


def test_the_configured_default_is_empty() -> None:
    """Asserted separately from `resolve_allowlist`, because a correct function
    with a non-empty shipped default is still the bug."""
    from fleeting.config import Config

    assert Config().activity.watch_allowlist == ""


# ---- resolution ------------------------------------------------------------


def test_a_real_directory_is_allowed(tmp_path) -> None:
    allowed, rejected = resolve_allowlist(str(tmp_path))
    assert allowed == [tmp_path]
    assert rejected == []


def test_a_missing_directory_is_rejected_with_a_reason(tmp_path) -> None:
    _, rejected = resolve_allowlist(str(tmp_path / "nope"))
    assert rejected[0]["reason"] == "does not exist"


def test_a_file_is_rejected_as_not_a_directory(tmp_path) -> None:
    """Pointing the scanner at a file is a typo, not a request."""
    f = touch(tmp_path, "notes.md")
    _, rejected = resolve_allowlist(str(f))
    assert rejected[0]["reason"] == "not a directory"


def test_system_directories_are_never_scanned(tmp_path) -> None:
    """/etc, /usr and the rest are refused whatever the allow-list says: a typo
    that loses a leading slash should not turn a project scan into a walk of the
    root filesystem."""
    for path in ("/etc", "/usr", "/", "/proc", "/home"):
        _, rejected = resolve_allowlist(path)
        assert rejected, f"{path} was not refused"
        assert "system directory" in rejected[0]["reason"]


def test_the_refusal_covers_every_system_path() -> None:
    """Pinned so adding a system directory to the set is a deliberate act."""
    for path in NEVER_SCAN:
        _, rejected = resolve_allowlist(path)
        assert rejected and "system directory" in rejected[0]["reason"]


def test_a_rejection_reports_both_what_was_typed_and_what_it_resolved_to(tmp_path) -> None:
    """`~` expansion goes wrong in ways the user needs to see."""
    _, rejected = resolve_allowlist("~/definitely-not-here")
    assert rejected[0]["path"] == "~/definitely-not-here"
    assert "definitely-not-here" in rejected[0]["resolved"]


def test_duplicates_are_scanned_once(tmp_path) -> None:
    allowed, _ = resolve_allowlist(f"{tmp_path}, {tmp_path}")
    assert allowed == [tmp_path]


def test_good_and_bad_entries_are_separated(tmp_path) -> None:
    """One bad entry must not take the good ones down with it."""
    allowed, rejected = resolve_allowlist(f"{tmp_path}, /etc")
    assert allowed == [tmp_path]
    assert len(rejected) == 1


# ---- the preview -----------------------------------------------------------


def test_the_preview_counts_without_naming_files(tmp_path) -> None:
    """A preview that listed filenames would leak the very thing the
    allow-list exists to gate."""
    touch(tmp_path / "proj", "secret-plan.md")
    since = datetime.now().astimezone() - timedelta(hours=1)
    body = preview_allowlist([tmp_path], since=since)
    assert body["total"] >= 1
    assert "secret-plan.md" not in str(body)


def test_the_preview_lists_projects_not_files(tmp_path) -> None:
    touch(tmp_path / "my-project", "a.py")
    body = preview_allowlist([tmp_path], since=datetime.now().astimezone() - timedelta(hours=1))
    assert "my-project" in body["dirs"][0]["projects"]


def test_the_preview_of_nothing_is_still_well_formed() -> None:
    body = preview_allowlist([], since=datetime.now().astimezone())
    assert body == {"total": 0, "dirs": [], "since": body["since"]}


# ---- the endpoint ----------------------------------------------------------


def test_the_preview_endpoint_works_with_an_empty_allowlist(client) -> None:
    body = client.get("/api/activity/files/preview").json()
    assert body["scanning"] is False
    assert body["total"] == 0


def test_the_files_endpoint_reports_what_is_being_scanned(client) -> None:
    """Otherwise a user cannot tell whether the allow-list took effect."""
    body = client.get("/api/activity/files").json()
    assert body["watching"] == []
    assert body["rejected"] == []


def test_the_files_endpoint_surfaces_rejections(client) -> None:
    client.put("/api/settings", json={"activity_watch_allowlist": "/etc, ~/nope-not-here"})
    body = client.get("/api/activity/files").json()
    reasons = [r["reason"] for r in body["rejected"]]
    assert any("system directory" in r for r in reasons)
    assert any("does not exist" in r for r in reasons)


def test_settings_round_trips_the_allowlist(client, tmp_path) -> None:
    client.put("/api/settings", json={"activity_watch_allowlist": str(tmp_path)})
    assert client.get("/api/settings").json()["activity_watch_allowlist"] == str(tmp_path)


# ---- and only the allow-list ------------------------------------------------


def test_a_directory_not_on_the_list_contributes_nothing(client, tmp_path) -> None:
    """The property the item asks for, end to end."""
    listed = tmp_path / "listed"
    unlisted = tmp_path / "unlisted"
    touch(listed / "project-a", "here.md")
    touch(unlisted / "project-b", "there.md")
    client.put("/api/settings", json={"activity_watch_allowlist": str(listed)})

    body = client.get("/api/activity/files").json()
    labels = [g["label"] for g in body["groups"]]
    assert "project-a" in labels
    assert "project-b" not in labels


def test_the_scan_reaches_freshly_written_files(client, tmp_path) -> None:
    """A zero result because the window is wrong looks exactly like a zero
    result because the allow-list is wrong."""
    listed = tmp_path / "listed"
    touch(listed / "project-a", f"note-{time.time_ns()}.md")
    client.put("/api/settings", json={"activity_watch_allowlist": str(listed)})
    body = client.get("/api/activity/files").json()
    assert body["total"] >= 1


PACKAGE = Path(__file__).resolve().parents[1] / "fleeting"


def _sources() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_no_module_reads_the_raw_watch_setting() -> None:
    """One invariant covering all seven call sites.

    There were seven places that turned `activity.watch_dirs` into a list of
    directories to scan. Fixing the one this ticket named would have left the
    other six able to read a directory the user never named, and every test for
    those six would have kept passing. A package-wide check is the only shape
    that actually holds the line — and it is cheap enough to keep.
    """
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in _sources()
        if "activity.watch_dirs" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these read the raw watch setting: {offenders}"


def test_no_module_splits_the_watch_setting_itself() -> None:
    """A module that hand-rolls `for p in cfg.activity.<field>.split(",")` has
    re-implemented the gate, and the allow-list is bypassed."""
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in _sources()
        if path.name != "files_activity.py"
        and "watch_allowlist" in path.read_text(encoding="utf-8")
        and 'watch_allowlist.split(",")' in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these bypass resolve_allowlist: {offenders}"


def test_the_activity_collector_uses_the_same_gate() -> None:
    """The collector's notion of "a project root" is a directory-reading input
    too, and it is reached on every poll rather than on a report click."""
    import inspect

    from fleeting import activity as act

    source = inspect.getsource(act)
    assert "resolve_allowlist" in source
    assert "cfg.watch_dirs" not in source