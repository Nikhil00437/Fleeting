"""#131 PDF ingestion and #132 audio ingestion.

Two parsers behind the queue from #119, and both are honest about when they
cannot do the job.

**#131 reads a PDF two ways, on purpose.** `pypdf` is the declared dependency
because it is pure Python and works everywhere; poppler's `pdftotext`, when it is
installed, reads more files — more encodings, more malformed structure — and is
used when present. A PDF with no extractable text is almost always a scan, and
that is reported as *scanned* with the file kept, rather than becoming an empty
note that looks like the import worked.

**OCR is not wired, and this says so rather than implying otherwise.** Turning
text extraction into OCR is a pipeline — rasterise, deskew, segment, recognise —
and the honest version of this item is a `pdf: scanned` result the user can act
on. Pretending otherwise would be worse than the gap.

**#132 reuses the whisper pipeline that already exists.** There is no second
transcriber here; the file is copied into the attachments directory and captured
normally, so segments, speakers, diarization and the activity collector all
behave exactly as they do for a voice memo.

**Neither source touches the network.** #131 is a path and #132 is a path; both
run offline, which is the point of a local-first app.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import ingest

log = logging.getLogger("fleeting.ingest.docs")

PDF_KIND = "pdf"
AUDIO_KIND = "audio"

# Characters kept. A long paper becomes a long note, and the note is what gets
# enriched — a 300,000-character paste is a context window problem for the model,
# not a reason to refuse the import.
MAX_TEXT_CHARS = 200_000

# Below this, a PDF has no extractable text and is almost certainly a scan.
MIN_TEXT_CHARS = 40

PDF_MIME_PREFIX = "application/pdf"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".mkv", ".webm"}


# ---- #131: PDF -------------------------------------------------------------


def extract_pdf(path: Path) -> dict[str, Any]:
    """Text out of a PDF. Never raises.

    Reports `method` so the caller can tell a real extraction from a scan, and
    `pages` because "12 pages, no text" is a very different thing from "12 pages
    of text".
    """
    text, method, pages = "", "none", 0
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        pages = len(reader.pages)
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        method = "pypdf"
    except Exception as exc:  # noqa: BLE001
        log.info("pypdf could not read %s: %s", path.name, exc)

    if len(text.strip()) < MIN_TEXT_CHARS:
        # Poppler reads more files — encodings and malformed structure especially.
        # Used when installed, never required.
        poppler = _pdftotext(path)
        if poppler is not None and len(poppler.strip()) > len(text.strip()):
            text, method = poppler, "pdftotext"

    clean = text.strip()
    if len(clean) < MIN_TEXT_CHARS:
        return {
            "text": clean,
            "title": path.stem,
            "pages": pages,
            "method": "scanned",
            "note": (
                "No extractable text — this looks like a scanned document. The file "
                "was kept; OCR is not wired up, so run it through another tool if you "
                "need the text."
            ),
        }
    return {
        "text": clean[:MAX_TEXT_CHARS],
        "title": path.stem,
        "pages": pages,
        "method": method,
        "note": "" if len(clean) <= MAX_TEXT_CHARS else f"truncated to {MAX_TEXT_CHARS} characters",
    }


def _pdftotext(path: Path) -> str | None:
    if not shutil.which("pdftotext"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.txt"
        try:
            subprocess.run(  # noqa: S603 - fixed argv, resolved binary, no shell
                ["pdftotext", "-q", str(path), str(out)],
                capture_output=True,
                timeout=120,
                check=True,
            )
            return out.read_text(encoding="utf-8", errors="replace")
        except (OSError, subprocess.SubprocessError):
            log.info("pdftotext gave up on %s", path.name)
            return None


def pdf_page_count(path: Path) -> int:
    info = _pdfinfo(path)
    if info is not None:
        return info.get("pages", 0)
    try:
        import pypdf

        return len(pypdf.PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 0


def _pdfinfo(path: Path) -> dict[str, Any] | None:
    if not shutil.which("pdfinfo"):
        return None
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, resolved binary, no shell
            ["pdfinfo", str(path)], capture_output=True, text=True, timeout=60, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out: dict[str, Any] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(":")
        if value.strip().isdigit():
            out[key.strip().lower()] = int(value.strip())
        elif value.strip():
            out[key.strip().lower()] = value.strip()
    return out


@ingest.register(PDF_KIND)
def parse_pdf_job(db: Any, cfg: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Import a PDF as a note, with its text."""
    path = Path(job["source"]).expanduser().resolve()
    if not path.is_file():
        return {"status": ingest.FAILED, "error": f"no such file: {path}"}
    if path.suffix.lower() != ".pdf":
        return {"status": ingest.FAILED, "error": "that is not a .pdf file"}
    if not path.read_bytes()[:5].startswith(b"%PDF"):
        return {
            "status": ingest.FAILED,
            "error": "that file does not start with %PDF — it may be a renamed something else",
        }

    key = f"file://{path}"
    if ingest.already_ingested(db, key, PDF_KIND):
        return {"status": ingest.SKIPPED, "detail": {"already_imported": True}}

    extracted = extract_pdf(path)
    note_id = _insert_doc(
        db,
        title=extracted["title"],
        body=extracted["text"] or f"[{path.name}] — no extractable text.",
        source_kind="pdf",
        source_path=path,
        extra={"pages": extracted["pages"], "method": extracted["method"]},
    )
    ingest.mark_ingested(db, key, PDF_KIND, extracted["title"])
    return {
        "status": ingest.DONE,
        "note_id": note_id,
        "detail": {
            "file": path.name,
            "chars": len(extracted["text"]),
            "pages": extracted["pages"],
            "method": extracted["method"],
            "note": extracted["note"],
            "explains": (
                "OCR is not wired up. A scanned PDF keeps its file and reports "
                "`scanned` rather than becoming an empty note."
            ),
        },
    }


# ---- #132: audio -----------------------------------------------------------


@ingest.register(AUDIO_KIND)
def parse_audio_job(db: Any, cfg: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Import a podcast or audio file by capturing it, not by transcribing it.

    The file is copied into the attachments directory and captured normally, so
    the existing whisper pipeline does segments, speakers and diarization exactly
    as it does for a voice memo. There is no second transcriber here to keep in
    step.
    """
    path = Path(job["source"]).expanduser().resolve()
    if not path.is_file():
        return {"status": ingest.FAILED, "error": f"no such file: {path}"}
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        return {
            "status": ingest.FAILED,
            "error": (
                f"{path.suffix or 'that'} is not a recognised audio file. Known: "
                + ", ".join(sorted(AUDIO_EXTENSIONS))
            ),
        }

    key = f"file://{path}"
    if ingest.already_ingested(db, key, AUDIO_KIND):
        return {"status": ingest.SKIPPED, "detail": {"already_imported": True}}

    stored = _stage_audio(db, cfg, path)
    if stored is None:
        return {"status": ingest.FAILED, "error": f"could not copy {path.name} into the app"}

    from ..db import new_id

    note_id = new_id()
    db.insert_note(
        {
            "id": note_id,
            "title": path.stem,
            "type": "voice",
            "raw_text": "",
            "status": "pending",
            "audio_path": str(stored),
            "source": {
                "imported_from": "audio",
                "imported_path": str(path),
                "original_name": path.name,
            },
        }
    )
    db.commit()
    ingest.mark_ingested(db, key, AUDIO_KIND, path.stem)
    return {
        "status": ingest.DONE,
        "note_id": note_id,
        "detail": {
            "file": path.name,
            "bytes": stored.stat().st_size,
            "explains": (
                "Captured as a normal voice note, so the existing transcription "
                "pipeline handles it and the transcript lands on the timeline."
            ),
        },
    }


def _stage_audio(db: Any, cfg: Any, path: Path) -> Path | None:
    """Copy into the app's attachments directory.

    Copied rather than referenced: the imported file may be on removable media,
    and a note whose audio path stops resolving the moment somebody ejects a disk
    is a broken note.
    """
    from ..db import new_id

    target_dir = Path(getattr(cfg, "attachments_dir", "") or "") or _default_attachments()
    target_dir = target_dir / new_id()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        shutil.copy2(path, target)
        return target
    except OSError as exc:
        log.warning("could not stage audio %s: %s", path, exc)
        return None


def _default_attachments() -> Path:
    from ..config import ATTACHMENTS_DIR

    return Path(ATTACHMENTS_DIR)


# ---- shared ---------------------------------------------------------------


def _insert_doc(
    db: Any,
    *,
    title: str,
    body: str,
    source_kind: str,
    source_path: Path,
    extra: dict[str, Any] | None = None,
) -> str:
    from ..db import new_id

    note_id = new_id()
    db.insert_note(
        {
            "id": note_id,
            "title": title or source_path.stem,
            "type": "text",
            "raw_text": body[:MAX_TEXT_CHARS],
            "status": "pending",
            "generated": 1,
            "source": {"imported_from": source_kind, "imported_path": str(source_path), **(extra or {})},
        }
    )
    db.commit()
    return note_id