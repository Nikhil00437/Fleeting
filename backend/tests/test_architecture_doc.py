"""ARCHITECTURE.md has to stay true, and prose does not stay true.

A diagram is the part of a codebase most likely to go quietly out of date: the
code moves, the picture keeps claiming the old shape, and a newcomer trusts it.
So the claims in it are checked against the code rather than trusted.

Not a spell-check of the prose — only the load-bearing nouns: event names,
statuses, stages, column names and the constants quoted in the diagrams. Those
are what a reader copies out and gets wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[2] / "ARCHITECTURE.md"
BACKEND = Path(__file__).resolve().parents[1] / "fleeting"
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


@pytest.fixture(scope="module")
def doc() -> str:
    assert DOC.exists(), "ARCHITECTURE.md is missing"
    return DOC.read_text(encoding="utf-8")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _published_events() -> set[str]:
    out: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        out.update(re.findall(r'publish\(\s*"([^"]+)"', _read(path)))
    return out


def _handled_events() -> set[str]:
    return set(
        re.findall(r'case\s+"([^"]+)"', _read(FRONTEND / "components" / "serverEvents.ts"))
    )


def _events_named_in(doc: str) -> set[str]:
    return set(
        re.findall(r"\b((?:note|task|activity|dailylog|whisper|embedding|collections)"
                   r"\.[a-z_]+)\b", doc)
    )


def test_every_event_the_doc_names_is_one_the_app_publishes(doc: str) -> None:
    """`note.created` in a diagram is a claim that a `bus.publish` exists."""
    unknown = _events_named_in(doc) - _published_events()
    assert not unknown, f"documented but never published: {sorted(unknown)}"


def test_every_event_the_doc_names_reaches_the_ui(doc: str) -> None:
    """The other half of the invariant.

    Not "the doc lists every event the app has" — a capture-pipeline document
    should not enumerate `activity.live` and `collections.changed`. But an
    event it *does* claim is published must also be one the SPA handles, or the
    diagram is describing a write whose effect is silently discarded.
    """
    unhandled = _events_named_in(doc) - _handled_events()
    assert not unhandled, f"published but the SPA ignores it: {sorted(unhandled)}"


def test_the_pipeline_events_are_actually_named(doc: str) -> None:
    """The two the whole diagram turns on."""
    assert {"note.created", "note.updated"} <= _events_named_in(doc)


def test_the_statuses_quoted_exist_in_the_processor(doc: str) -> None:
    process = _read(BACKEND / "process.py")
    for status in ("pending", "processing", "done", "failed"):
        if status in doc:
            assert f'"{status}"' in process, f"status {status!r} is no longer used"


def test_the_transcription_precedes_enrichment(doc: str) -> None:
    """The order is the claim the diagram makes.

    A check on stage *names* was here and was removed: the diagram says
    "transcribe" and "enrich" where the code says "transcribing" and
    "enriching", so the extraction matched nothing and the assertion was
    vacuously true. That is worse than having no check — it looks like
    coverage. Order, on the other hand, is what the diagram is actually for,
    and it is checkable.
    """
    process = _read(BACKEND / "process.py")
    transcribe_at = process.find("transcribe_file")
    enrich_at = process.find("heuristic_enrich", transcribe_at)
    if transcribe_at == -1:
        # No transcription in the pipeline at all any more — the diagram is
        # describing a step that no longer exists.
        assert "transcribe" not in doc.lower() or "only if type=voice" in doc
        return
    assert enrich_at > transcribe_at, "enrichment now runs before transcription"

    # And the document shows them in that order too.
    doc_text = doc.lower()
    assert doc_text.index("transcribe") < doc_text.index("enrich(")


def test_the_column_names_quoted_exist(doc: str) -> None:
    """`generated`, `processed_at` and `enrich_ms` are load-bearing in the text."""
    db = _read(BACKEND / "db.py")
    for column in ("generated", "processed_at", "enrich_ms", "raw_text", "audio_path"):
        if column in doc:
            assert column in db, f"column {column!r} is quoted but not in db.py"


def test_the_worker_count_matches_the_claim(doc: str) -> None:
    """The doc says 2 and a comment says why. If it moves, both must move."""
    process = _read(BACKEND / "process.py")
    match = re.search(r"WORKERS\s*=\s*(\d+)", process)
    assert match, "Processor.WORKERS is gone"
    assert f"`{match.group(1)} workers`" in doc or f"({match.group(1)} workers" in doc, (
        f"the doc does not state the worker count ({match.group(1)})"
    )


def test_the_queue_cap_is_not_claimed_wrong(doc: str) -> None:
    process = _read(BACKEND / "process.py")
    cap = re.search(r"maxsize\s*=\s*(\d+)", process)
    if cap and "cap" in doc:
        assert str(cap.group(1)) in doc, (
            f"the doc quotes a queue cap that is now {cap.group(1)}"
        )


def test_the_readme_is_linked_rather_than_duplicated(doc: str) -> None:
    """Two files listing the same directory tree is how they drift apart."""
    assert "README.md" in doc
    assert "process.py" in doc, "the pipeline module should be findable from here"


def test_the_readme_links_back_to_the_architecture_doc() -> None:
    """An architecture doc nobody is pointed at does not get read, let alone
    kept true. Cheap to check, and it is the half of the pair that rots first."""
    readme = Path(__file__).resolve().parents[2] / "README.md"
    assert "ARCHITECTURE.md" in readme.read_text(encoding="utf-8")