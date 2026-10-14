"""#492: chunked enrichment, and an honest account of what was covered.

**What goes wrong without this.** A long paste goes to the model as one prompt.
It either blows the context window — a hard failure that drops to heuristics, so
the note looks like it was never enriched — or the provider truncates it, which
is worse: a confident summary of the first tenth presented as though it covered
everything. The second one is the reason the coverage report exists at all.

The properties pinned here, in order of how badly each would hurt:

1. **Truncation is reported.** `ENRICH_MAX_CHUNKS` bounds the work, so a book
   pasted in becomes five chunks. The result says so. A summary of the first
   five chunks is useful *provided the user knows that is what it is*.
2. **Chunks break on paragraphs, not offsets.** A chunk ending mid-sentence
   produces a summary of a sentence that does not exist.
3. **Merging keeps information.** A tag that appears in the fourth chunk is not
   dropped for having arrived late, while title and summary come from the
   *first* chunk that produced one — a summary of chunk four describes the wrong
   half of the text.
4. **One unavailable chunk fails the whole note.** Partial enrichment reported
   as success is the worst of the three outcomes.
"""

from __future__ import annotations

from typing import Any, Coroutine

import anyio
import pytest

from fleeting.config import LLMConfig
from fleeting.services import llm


def paras(count: int, size: int = 200) -> str:
    """Paragraphs made of words, so a chunk ending mid-word is detectable."""
    filler = " ".join(f"w{j}" for j in range(size // 3))
    return "\n\n".join(f"Paragraph {i}. {filler}" for i in range(count))


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive a coroutine to completion.

    The suite has no async tests and no asyncio mode configured, so these are
    sync tests that await explicitly rather than a pytest-config change made in
    a feature branch.
    """
    return anyio.run(lambda: coro)


# ---- chunking --------------------------------------------------------------


def test_short_text_is_one_chunk() -> None:
    assert llm.chunk_text("a short note") == ["a short note"]


def test_empty_text_is_no_chunks() -> None:
    """Not one empty chunk: an empty chunk is a model call that can only return
    nothing."""
    assert llm.chunk_text("   ") == []


def test_long_text_is_split() -> None:
    assert len(llm.chunk_text(paras(60))) > 1


def test_no_chunk_exceeds_the_limit() -> None:
    for chunk in llm.chunk_text(paras(60), limit=1000):
        assert len(chunk) <= 1000


def test_nothing_is_dropped_when_nothing_is_truncated() -> None:
    original = paras(30)
    chunks, truncated = llm._chunk(original)
    assert truncated is False
    seen = " ".join(chunks)
    for i in range(30):
        assert f"Paragraph {i}." in seen


def test_the_chunk_count_is_capped() -> None:
    """Without a cap, pasting a book is fifty sequential model calls on a queue
    with two workers."""
    assert len(llm.chunk_text(paras(2000))) == llm.ENRICH_MAX_CHUNKS


def test_chunks_break_on_paragraphs() -> None:
    """A chunk ending mid-paragraph produces a summary of a sentence that does
    not exist.

    Every piece of every chunk must therefore be a whole paragraph — asserted
    by reconstructing the original text from the chunks and comparing it, which
    catches both splitting mid-paragraph and silently dropping one.
    """
    # Small enough to fit inside ENRICH_MAX_CHUNKS: this test is about *where*
    # the boundaries fall, and truncation would hide that behind a cap.
    original = paras(8, 300)
    chunks = llm.chunk_text(original, limit=1000)
    assert len(chunks) > 1
    assert "\n\n".join(chunks) == original
    assert all(c.startswith("Paragraph ") for c in chunks)


def test_one_huge_paragraph_is_still_split() -> None:
    """No newlines at all is what pasting from a terminal looks like."""
    chunks = llm.chunk_text("y" * 10_000, limit=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


def test_a_huge_paragraph_of_sentences_splits_on_sentences() -> None:
    text = " ".join(f"Sentence number {i} has some words in it." for i in range(400))
    chunks = llm.chunk_text(text, limit=800)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)
    assert "Sentence" in chunks[0] and "Sentence" in chunks[-1]
def test_truncation_is_flagged_exactly_when_content_is_dropped() -> None:
    """The invariant, over a matrix of shapes.

    Checking one size would let a redundant second code path mask a missing
    flag: the loop can detect truncation either by running out of chunks or by
    finding leftovers, and for any single input only one of those fires. This
    sweeps both, plus the sizes in between where neither is obvious.
    """

    def norm(text: str) -> str:
        return " ".join(text.split())

    for limit in (300, 800, 2000):
        for max_chunks in (1, 2, 3, 5):
            for count in (1, 4, 9, 30):
                original = paras(count)
                chunks, truncated = llm._chunk(original, limit=limit, max_chunks=max_chunks)
                # Compared on normalised text: chunk boundaries drop the
                # paragraph separators by design, so a byte comparison would
                # flag every chunked note as truncated.
                dropped = norm(original) not in norm(" ".join(chunks))
                assert dropped == truncated or (dropped and truncated), (
                    f"limit={limit} max_chunks={max_chunks} count={count}: "
                    f"dropped={dropped} truncated={truncated}"
                )


def test_truncation_is_flagged_by_the_chunker_not_inferred() -> None:
    """Byte arithmetic cannot tell truncation from separator loss — the flag
    comes from the loop that actually stopped."""
    _, truncated = llm._chunk(paras(2000))
    assert truncated is True


def test_chunking_never_loses_the_start() -> None:
    """Truncation is fine — it is reported. Dropping the beginning is not, and
    would make the summary describe the wrong part."""
    chunks = llm.chunk_text(paras(2000))
    assert "Paragraph 0" in chunks[0]


# ---- merging ---------------------------------------------------------------


def test_tags_from_every_chunk_survive() -> None:
    """A tag that appears in the fourth chunk is not dropped for arriving late."""
    merged = llm.merge_enrichment(
        [{"tags": ["a"]}, {"tags": []}, {"tags": ["b"]}, {"tags": ["c"]}]
    )
    assert merged["tags"] == ["a", "b", "c"]


def test_duplicate_tags_appear_once() -> None:
    merged = llm.merge_enrichment([{"tags": ["a", "b"]}, {"tags": ["b", "a"]}])
    assert merged["tags"] == ["a", "b"]


def test_action_items_concatenate_and_dedupe() -> None:
    merged = llm.merge_enrichment(
        [{"action_items": ["one"]}, {"action_items": ["one", "two"]}]
    )
    assert merged["action_items"] == ["one", "two"]


def test_the_title_comes_from_the_first_chunk_that_produced_one() -> None:
    merged = llm.merge_enrichment(
        [{"title": "", "summary": ""}, {"title": "Second", "summary": "Later"}]
    )
    assert merged["title"] == "Second"
    # …and so does the summary: a summary of chunk two describes the wrong half.
    assert merged["summary"] == "Later"


def test_the_summary_is_not_taken_from_a_later_chunk_when_an_earlier_one_has_one() -> None:
    merged = llm.merge_enrichment([{"summary": "First"}, {"summary": "Later"}])
    assert merged["summary"] == "First"


def test_merging_nothing_is_still_a_well_formed_result() -> None:
    merged = llm.merge_enrichment([])
    assert merged["tags"] == [] and merged["title"] == ""


def test_empty_and_missing_keys_do_not_crash() -> None:
    merged = llm.merge_enrichment([{"tags": None}, {}, {"action_items": ["x"]}])
    assert merged["tags"] == []
    assert merged["action_items"] == ["x"]


# ---- the whole call --------------------------------------------------------


@pytest.fixture()
def recording_llm(monkeypatch):
    """Captures what each chunk was actually sent, so 'was it chunked?' is
    asserted on the payload rather than on a return value."""
    seen: list[str] = []

    async def fake_chain(text, cfg, **kwargs):
        seen.append(text)
        return {"title": f"title of {text[:12]}", "summary": "s", "tags": [text[:6]], "action_items": []}

    monkeypatch.setattr(llm, "enrich_chain", fake_chain)
    return seen


def test_a_long_note_is_enriched_in_chunks(recording_llm) -> None:
    enriched, coverage = run(llm.enrich_long_text(paras(60), LLMConfig(provider="local")))
    assert len(recording_llm) > 1
    assert coverage["chunked"] is True
    assert all(len(c) <= llm.ENRICH_CHUNK_CHARS for c in recording_llm)
    assert enriched["tags"]  # merged, not overwritten


def test_a_short_note_is_enriched_in_one_call(recording_llm) -> None:
    _, coverage = run(llm.enrich_long_text("just a short note", LLMConfig(provider="local")))
    assert recording_llm == ["just a short note"]
    assert coverage["chunked"] is False
    assert coverage["truncated"] is False


def test_truncation_is_reported_not_hidden(recording_llm) -> None:
    """The whole point: a summary of the first five chunks is a useful answer
    provided the user knows that is what it is."""
    text = paras(3000)
    _, coverage = run(llm.enrich_long_text(text, LLMConfig(provider="local")))
    assert coverage["truncated"] is True
    assert coverage["covered"] < coverage["total"]
    assert coverage["chunks"] == llm.ENRICH_MAX_CHUNKS


def test_full_coverage_reports_no_truncation(recording_llm) -> None:
    # Long enough to chunk, short enough to fit inside ENRICH_MAX_CHUNKS — the
    # point is full coverage, not truncation.
    _, coverage = run(llm.enrich_long_text(paras(30), LLMConfig(provider="local")))
    assert coverage["chunked"] is True
    assert coverage["truncated"] is False
    assert coverage["chunks"] > 1
    # Not `covered == total`: chunk boundaries drop the paragraph separators, so
    # the byte counts legitimately differ. What matters is that nothing was
    # dropped — which is what `truncated` now reports directly.
    assert coverage["covered"] <= coverage["total"]


def test_one_unavailable_chunk_fails_the_whole_note(monkeypatch) -> None:
    """Partial enrichment reported as success is the worst of the three
    outcomes — the caller must fall back for the entire note."""
    calls = {"n": 0}

    async def flaky(text, cfg, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise llm.LLMUnavailable("second chunk failed")
        return {"title": "t", "summary": "s", "tags": [], "action_items": []}

    monkeypatch.setattr(llm, "enrich_chain", flaky)
    with pytest.raises(llm.LLMUnavailable):
        run(llm.enrich_long_text(paras(60), LLMConfig(provider="local")))


def test_empty_text_does_not_call_the_model(monkeypatch) -> None:
    async def never(text, cfg, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(llm, "enrich_chain", never)
    enriched, coverage = run(llm.enrich_long_text("  ", LLMConfig(provider="local")))
    assert enriched["tags"] == []
    assert coverage["covered"] == 0


def test_every_coverage_report_has_the_same_keys(monkeypatch) -> None:
    """A report whose shape depends on how long the text happened to be is a
    report every caller has to guard, and the one that is not guarded raises
    `KeyError` at the worst possible moment."""

    async def fake(text, cfg, **kwargs):
        return {"title": "t", "summary": "s", "tags": [], "action_items": []}

    monkeypatch.setattr(llm, "enrich_chain", fake)
    cfg = LLMConfig(provider="local")
    seen = []
    for text in ("", "   ", "a short note", paras(12)):
        _, coverage = run(llm.enrich_long_text(text, cfg))
        seen.append(tuple(sorted(coverage)))
    assert len(set(seen)) == 1

# ---- the warning reaches the user ------------------------------------------


def test_a_truncated_enrichment_says_so(client, monkeypatch) -> None:
    """An enrichment that only read part of the note has to say so where the
    user sees it, not only in the database."""
    from conftest import wait_done

    from fleeting import process as proc

    async def fake_long(text, cfg, **kwargs):
        return (
            {"title": "t", "summary": "s", "tags": [], "action_items": []},
            {"chunked": True, "chunks": 5, "covered": 4000, "total": 99_000, "truncated": True},
        )

    monkeypatch.setattr(proc.llm, "enrich_long_text", fake_long)
    note = client.post("/api/capture/text", json={"text": "a long paste " * 500}).json()
    row = wait_done(client, note["id"])
    assert "first 5 sections" in (row.get("source") or {}).get("enrichment_warning", "")
    assert "4000" in row["source"]["enrichment_warning"]


def test_a_short_note_gets_no_such_warning(client) -> None:
    from conftest import wait_done

    note = client.post("/api/capture/text", json={"text": "just a short thought"}).json()
    row = wait_done(client, note["id"])
    assert "enrichment_warning" not in (row.get("source") or {})
