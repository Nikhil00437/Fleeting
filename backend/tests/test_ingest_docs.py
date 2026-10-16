"""#131 PDF ingestion and #132 audio ingestion.

The theme is honesty about failure, because both features can half-work and look
like they worked:

1. **A scanned PDF reports `scanned`, keeps the file, and says OCR is not
   wired.** Turning extraction into OCR is a pipeline — rasterise, deskew,
   segment, recognise — and an empty note that looks like a successful import is
   worse than a stated gap.
2. **A file that is not a PDF is refused before extraction.** Checking `%PDF` is
   what stops a renamed `.mp4` becoming a zero-page note.
3. **Audio is captured, not transcribed here.** There is no second transcriber
   to keep in step with the existing one.
4. **The file is copied, not referenced.** A note whose audio path stops
   resolving because somebody ejected a disk is a broken note.

Neither source touches the network. Both run offline, which is the point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleeting.services import ingest, ingest_docs


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "d.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    paths = PathsConfig(vault_dir=str(tmp_path / "vault"))
    paths.attachments_dir = str(tmp_path / "attachments")
    return paths


def real_pdf(tmp_path, text: str | None = None) -> Path:
    """A minimal but genuinely valid one-page PDF.

    Written by hand rather than with a library so the test does not depend on the
    thing it is testing. `reportlab` would be a second dependency for a fixture.
    """
    # `text is None` rather than `text or`: an empty string is the whole
    # point of the scanned-PDF tests, and `or` turned it back into the default.
    content = "Hello from a PDF page. " * 20 if text is None else text
    stream = content.replace("(", r"\(").replace(")", r"\)")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream) + 30).encode() + b" >>\nstream\nBT /F1 12 Tf 72 720 Td ("
        + stream.encode("latin-1", "replace")
        + b") Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    path = tmp_path / "paper.pdf"
    path.write_bytes(bytes(out))
    return path


def run(db, cfg, kind, path):
    job = ingest.enqueue(db, kind, str(path))
    return ingest.run_one(db, cfg, job["id"])


# ---- #131: PDF -------------------------------------------------------------


def test_pdf_text_is_extracted(db, cfg, tmp_path) -> None:
    done = run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))
    assert done["status"] == ingest.DONE
    note = db.get_note(done["note_id"])
    assert "Hello from a PDF page" in note["raw_text"]


def test_the_page_count_is_reported(db, cfg, tmp_path) -> None:
    assert run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))["detail"]["pages"] == 1


def test_the_extraction_method_is_reported(db, cfg, tmp_path) -> None:
    """`pypdf` or `pdftotext` — which one read it is useful when a file needs
    another try."""
    assert run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))["detail"]["method"] in (
        "pypdf",
        "pdftotext",
    )


def test_a_pdf_note_joins_the_pipeline(db, cfg, tmp_path) -> None:
    done = run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))
    assert db.get_note(done["note_id"])["status"] == "pending"


def test_importing_the_same_pdf_twice_is_skipped(db, cfg, tmp_path) -> None:
    path = real_pdf(tmp_path)
    run(db, cfg, ingest_docs.PDF_KIND, path)
    assert run(db, cfg, ingest_docs.PDF_KIND, path)["status"] == ingest.SKIPPED


def test_a_missing_file_is_refused(db, cfg, tmp_path) -> None:
    assert run(db, cfg, ingest_docs.PDF_KIND, tmp_path / "gone.pdf")["status"] == ingest.FAILED


def test_a_renamed_non_pdf_is_refused(db, cfg, tmp_path) -> None:
    """Checking `%PDF` is what stops a renamed `.mp4` becoming a zero-page note."""
    fake = tmp_path / "not-really.pdf"
    fake.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 500)
    done = run(db, cfg, ingest_docs.PDF_KIND, fake)
    assert done["status"] == ingest.FAILED
    assert "%PDF" in done["error"]


def test_the_wrong_extension_is_refused(db, cfg, tmp_path) -> None:
    f = tmp_path / "thing.pdf"
    f.write_bytes(b"%PDF-1.4 not really")
    f2 = tmp_path / "thing.txt"
    f2.write_bytes(b"%PDF-1.4")
    assert run(db, cfg, ingest_docs.PDF_KIND, f2)["status"] == ingest.FAILED


def test_a_corrupt_pdf_does_not_crash_the_import(db, cfg, tmp_path) -> None:
    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-1.4 truncated garbage that is not a pdf")
    done = run(db, cfg, ingest_docs.PDF_KIND, f)
    assert done["status"] == ingest.DONE, "a broken file still becomes a note"


def test_a_pdf_with_no_text_is_reported_as_scanned(db, cfg, tmp_path) -> None:
    """An empty note that looks like a successful import is worse than a stated
    gap."""
    blank = real_pdf(tmp_path, text="")
    done = run(db, cfg, ingest_docs.PDF_KIND, blank)
    assert done["detail"]["method"] == "scanned"
    assert "OCR is not wired" in done["detail"]["note"]


def test_a_scanned_pdf_still_becomes_a_note(db, cfg, tmp_path) -> None:
    """The file is kept. The user can act on `scanned`; they cannot act on
    nothing."""
    done = run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path, text=""))
    note = db.get_note(done["note_id"])
    assert note is not None
    assert "no extractable text" in note["raw_text"]


def test_the_ocr_gap_is_stated_in_the_result(db, cfg, tmp_path) -> None:
    """Not just in the method name — in a sentence the user reads.

    Asserting the word `OCR` is not enough: a mutation that says "OCR ran"
    contains it too, and that is precisely the claim this test exists to
    prevent. The gap has to be stated as *not done*.
    """
    done = run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))
    explains = done["detail"]["explains"].lower()
    assert "ocr" in explains
    assert "not wired" in explains or "not implemented" in explains


# ---- #132: audio -----------------------------------------------------------


def test_an_audio_file_is_captured(db, cfg, tmp_path) -> None:
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    done = run(db, cfg, ingest_docs.AUDIO_KIND, audio)
    assert done["status"] == ingest.DONE
    assert db.get_note(done["note_id"])["type"] == "voice"


def test_the_audio_is_copied_not_referenced(db, cfg, tmp_path) -> None:
    """A note whose audio path stops resolving because somebody ejected a disk is
    a broken note."""
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    done = run(db, cfg, ingest_docs.AUDIO_KIND, audio)
    stored = Path(db.get_note(done["note_id"])["audio_path"])
    assert stored.exists()
    assert stored != audio


def test_the_captured_note_is_pending_for_transcription(db, cfg, tmp_path) -> None:
    """There is no second transcriber here; the existing pipeline handles it."""
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    done = run(db, cfg, ingest_docs.AUDIO_KIND, audio)
    assert db.get_note(done["note_id"])["status"] == "pending"


def test_the_original_name_is_kept(db, cfg, tmp_path) -> None:
    audio = tmp_path / "Episode 12 - the good bit.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    done = run(db, cfg, ingest_docs.AUDIO_KIND, audio)
    assert db.get_note(done["note_id"])["source"]["original_name"] == audio.name


def test_importing_the_same_audio_twice_is_skipped(db, cfg, tmp_path) -> None:
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    run(db, cfg, ingest_docs.AUDIO_KIND, audio)
    assert run(db, cfg, ingest_docs.AUDIO_KIND, audio)["status"] == ingest.SKIPPED


def test_an_unknown_audio_extension_lists_what_is_known(db, cfg, tmp_path) -> None:
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    error = run(db, cfg, ingest_docs.AUDIO_KIND, other)["error"]
    assert ".mp3" in error


def test_a_missing_audio_file_is_refused(db, cfg, tmp_path) -> None:
    assert run(db, cfg, ingest_docs.AUDIO_KIND, tmp_path / "gone.mp3")["status"] == ingest.FAILED


def test_several_audio_formats_are_accepted() -> None:
    for ext in (".mp3", ".m4a", ".wav", ".flac", ".opus", ".ogg"):
        assert ext in ingest_docs.AUDIO_EXTENSIONS


# ---- no network -----------------------------------------------------------


def test_neither_source_touches_the_network(db, cfg, tmp_path, monkeypatch) -> None:
    """Both run offline, which is the point of a local-first app."""
    from fleeting.services import fetch

    def explode(*a, **k):
        raise AssertionError("PDF and audio import must not fetch anything")

    monkeypatch.setattr(fetch, "fetch", explode)
    run(db, cfg, ingest_docs.PDF_KIND, real_pdf(tmp_path))
    audio = tmp_path / "e.mp3"
    audio.write_bytes(b"ID3")
    run(db, cfg, ingest_docs.AUDIO_KIND, audio)


# ---- the endpoints ---------------------------------------------------------


def test_a_pdf_can_be_queued_through_the_api(client, tmp_path) -> None:
    job = client.post("/api/ingest", json={"kind": "pdf", "source": str(real_pdf(tmp_path))}).json()
    done = client.post(f"/api/ingest/jobs/{job['id']}/run").json()
    assert done["status"] == "done"


def test_audio_through_the_api(client, tmp_path) -> None:
    client.app.state.st.cfg.paths.attachments_dir = str(tmp_path / "att")
    audio = tmp_path / "ep.mp3"
    audio.write_bytes(b"ID3" + b"\x00" * 400)
    job = client.post("/api/ingest", json={"kind": "audio", "source": str(audio)}).json()
    assert client.post(f"/api/ingest/jobs/{job['id']}/run").json()["status"] == "done"