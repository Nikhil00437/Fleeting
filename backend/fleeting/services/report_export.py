"""#74 Report export: Markdown and PDF renderers.

Markdown export produces a clean standalone document ready for filing or sharing.
PDF export converts the report to a formatted document using headless Chromium when
available, and falls back to a pure-Python compliant PDF generator so it works in any
environment without external dependencies.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile

log = logging.getLogger("fleeting.report_export")


def render_markdown_export(day: str, report_md: str) -> str:
    """Format markdown report with export frontmatter / header."""
    md = (report_md or "").strip()
    if not md:
        md = f"# Daily Digest — {day}\n\n*No activity recorded.*"
    return md + "\n"


def _normalize_text_for_pdf(text: str) -> str:
    """Normalize unicode punctuation and symbols to ASCII for standard PDF Helvetica."""
    replacements = {
        "\u2014": "--",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u2026": "...",
        "\u00a0": " ",
        "·": "-",
        "×": "x",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("ascii", errors="replace").decode("ascii")


def render_pure_python_pdf(day: str, report_md: str) -> bytes:
    """Zero-dependency pure-Python PDF-1.4 generator."""
    raw_lines = (report_md or "").strip().splitlines()
    if not raw_lines:
        raw_lines = [f"# Daily Digest — {day}", "", "No activity recorded."]

    pages_stream_lines: list[list[str]] = [[]]
    current_page_lines = pages_stream_lines[0]
    y = 730

    def add_page():
        nonlocal current_page_lines, y
        current_page_lines = []
        pages_stream_lines.append(current_page_lines)
        y = 730

    for raw in raw_lines:
        line = _normalize_text_for_pdf(raw.strip())
        if not line:
            y -= 10
            if y < 60:
                add_page()
            continue

        if line.startswith("# "):
            font = "/F2 16 Tf"
            text = line[2:].strip()
            dy = 22
        elif line.startswith("## "):
            font = "/F2 13 Tf"
            text = line[3:].strip()
            dy = 18
        elif line.startswith("### "):
            font = "/F2 11 Tf"
            text = line[4:].strip()
            dy = 15
        else:
            font = "/F1 10 Tf"
            text = line
            dy = 13

        # Word wrap if text is long
        words = text.split(" ")
        wrapped_lines: list[str] = []
        cur_wrap = ""
        for w in words:
            if len(cur_wrap) + len(w) + 1 > 85:
                wrapped_lines.append(cur_wrap)
                cur_wrap = w
            else:
                cur_wrap = f"{cur_wrap} {w}".strip()
        if cur_wrap:
            wrapped_lines.append(cur_wrap)

        for wl in wrapped_lines:
            if y < 60:
                add_page()
            escaped = wl.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            current_page_lines.append(f"BT {font} 54 {y} Td ({escaped}) Tj ET")
            y -= dy

    # Build PDF catalog with pages
    total_pages = len(pages_stream_lines)
    objects: list[bytes] = []

    # Object 1: Catalog
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")

    # Object 2: Pages root
    kids_refs = " ".join(f"{3 + i} 0 R" for i in range(total_pages))
    objects.append(f"<< /Type /Pages /Kids [{kids_refs}] /Count {total_pages} >>".encode())

    # Pages definitions and content streams
    # Fonts are placed at objects after the pages & contents
    font_f1_idx = 3 + (total_pages * 2)
    font_f2_idx = font_f1_idx + 1

    for i in range(total_pages):
        page_obj_idx = 3 + i
        content_obj_idx = 3 + total_pages + i

        page_dict = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_obj_idx} 0 R "
            f"/Resources << /Font << /F1 {font_f1_idx} 0 R /F2 {font_f2_idx} 0 R >> >> >>"
        )
        objects.append(page_dict.encode())

    for i in range(total_pages):
        stream_content = "\n".join(pages_stream_lines[i]).encode("ascii")
        stream_obj = (
            b"<< /Length " + str(len(stream_content)).encode() + b" >>\nstream\n"
            + stream_content + b"\nendstream"
        )
        objects.append(stream_obj)

    # Fonts
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    out: list[bytes] = [b"%PDF-1.4\n"]
    offsets: list[int] = []
    for idx, obj in enumerate(objects, 1):
        offsets.append(sum(len(x) for x in out))
        out.append(f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n")

    xref_offset = sum(len(x) for x in out)
    out.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.append(f"{off:010d} 00000 n \n".encode())
    out.append(
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode() + b"\n%%EOF\n"
    )
    return b"".join(out)


def render_html_for_export(day: str, report_md: str) -> str:
    """Render markdown into clean printable HTML."""
    import html
    import re

    lines = (report_md or "").strip().splitlines()
    body_html_parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            body_html_parts.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            body_html_parts.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            body_html_parts.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith(("- ", "* ")):
            # convert bold **text**
            text = html.escape(stripped[2:])
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
            body_html_parts.append(f"<li>{text}</li>")
        else:
            text = html.escape(stripped)
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
            text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
            text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
            body_html_parts.append(f"<p>{text}</p>")

    content = "\n".join(body_html_parts)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Daily Digest — {html.escape(day)}</title>
<style>
  @page {{
    size: letter;
    margin: 20mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1a1a;
    line-height: 1.5;
    font-size: 13px;
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
  }}
  h1 {{
    font-size: 22px;
    border-bottom: 2px solid #e5e5e5;
    padding-bottom: 8px;
    margin-bottom: 16px;
    color: #111;
  }}
  h2 {{
    font-size: 16px;
    margin-top: 20px;
    margin-bottom: 8px;
    color: #222;
  }}
  h3 {{
    font-size: 14px;
    margin-top: 14px;
    margin-bottom: 6px;
  }}
  p {{
    margin: 6px 0;
  }}
  li {{
    margin: 4px 0;
  }}
  code {{
    background: #f4f4f5;
    padding: 2px 4px;
    border-radius: 4px;
    font-size: 12px;
  }}
  strong {{
    color: #000;
  }}
</style>
</head>
<body>
{content}
</body>
</html>"""


def render_pdf_export(day: str, report_md: str) -> bytes:
    """Render PDF using Chromium if available, falling back to pure Python."""
    chromium_path = shutil.which("chromium") or shutil.which("google-chrome")
    if chromium_path:
        tmp_html = None
        tmp_pdf = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
                f.write(render_html_for_export(day, report_md))
                tmp_html = f.name
            tmp_pdf = tmp_html.replace(".html", ".pdf")

            cmd = [
                chromium_path,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--print-to-pdf={tmp_pdf}",
                tmp_html,
            ]
            res = subprocess.run(cmd, capture_output=True, timeout=10)
            if res.returncode == 0 and os.path.exists(tmp_pdf) and os.path.getsize(tmp_pdf) > 0:
                with open(tmp_pdf, "rb") as pf:
                    return pf.read()
        except Exception as exc:
            log.warning("Chromium PDF export failed, using fallback: %s", exc)
        finally:
            for p in (tmp_html, tmp_pdf):
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    return render_pure_python_pdf(day, report_md)
