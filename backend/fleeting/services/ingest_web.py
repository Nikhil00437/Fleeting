"""#129 RSS/Atom ingestion, and #130 a read-later queue.

Two parsers behind the one queue from #119. Both fetch a URL and turn the
response into notes; what they do with the bytes differs.

**A feed item becomes a note, not a note per item.** An RSS feed is 200 entries;
importing them as 200 notes would bury everything the user already had. Each item
becomes a pending capture so it joins the normal pipeline — tags, summary,
embedding — rather than being filed raw.

**Seen items are remembered by `guid`, not by URL.** Feeds re-serve the same
entries forever, and a URL changes when a title is edited. `guid` is what the
publisher says identifies the entry, so that is what is keyed on; the URL is the
fallback for feeds that omit it.

**Read-later is a queue, and the queue is the point.** Saving a URL is a
different act from importing a feed: you are not subscribed, you want it in your
notes. It extracts readable text from the page rather than saving a link, because
a link that dies is a link you cannot read.

**Article extraction is best-effort and says so.** Stripping `<script>`,
`<style>` and `<nav>` and taking the densest `<p>`-heavy chunk gets a usable
article from most pages and a poor one from the rest. A `method` field on the
result says which happened, because "here is your article" from a
navigation-scrape is a lie the user cannot detect.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

from . import ingest

log = logging.getLogger("fleeting.ingest.web")

FEED_KIND = "rss"
URL_KIND = "url"

# Entries per feed, newest first. A feed is not an archive, and a 2,000-entry
# backfill is nobody's idea of a subscription.
MAX_ENTRIES = 50

# Characters of extracted article text. Beyond this the note is a wall.
MAX_ARTICLE_CHARS = 40_000

# Below this, the "article" is almost certainly navigation chrome.
MIN_ARTICLE_CHARS = 400


# ---- #129: feeds -----------------------------------------------------------


def parse_feed(xml: str, base_url: str = "") -> list[dict[str, Any]]:
    """RSS 2.0 and Atom, from one document.

    Element names are matched without namespace prefixes because a feed that
    declares `atom:` and one that does not should not need two parsers.
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml.strip())
    except ET.ParseError as exc:
        raise ValueError(f"that is not valid XML: {exc}") from exc

    entries: list[dict[str, Any]] = []
    for node in root.iter():
        tag = _tag(node.tag)
        if tag not in ("item", "entry"):
            continue
        entry = {
            "title": _text(node, "title"),
            "link": _link(node, base_url),
            "summary": _text(node, "description") or _text(node, "summary"),
            "content": _text(node, "encoded") or _text(node, "content"),
            "guid": _text(node, "guid") or _text(node, "id"),
            "published": _text(node, "pubDate") or _text(node, "published") or _text(node, "updated"),
        }
        if entry["guid"]:
            entry["guid"] = entry["guid"].strip()
        entries.append(entry)
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


def _tag(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _text(node: Any, name: str) -> str:
    # Compared lower-cased: `_tag` lower-cases the element, so looking for
    # `pubDate` against a tag normalised to `pubdate` never matched and the
    # published date silently came out empty.
    wanted = name.lower()
    for child in node:
        if _tag(child.tag) == wanted:
            return "".join(child.itertext()).strip()
    # Atom puts the value in an attribute.
    value = node.attrib.get(name)
    return value.strip() if value else ""


def _link(node: Any, base_url: str) -> str:
    for child in node:
        if _tag(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if (child.text or "").strip():
            return child.text.strip()
    return _text(node, "link") or _text(node, "origLink") or base_url


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def _strip_tags(text: str) -> str:
    """Tags out, entities decoded, whitespace collapsed.

    Deliberately simple: a feed's `<description>` is a paragraph of prose with
    the occasional `<a>` or `<img>`, and a real HTML parser here would be a
    dependency bought for a job `re` does.
    """
    import html as htmllib

    return _WS.sub(" ", htmllib.unescape(_TAG.sub(" ", text))).strip()


def _summary_of(entry: dict[str, Any]) -> str:
    """Whatever prose the feed gave us, with tags stripped."""
    return _strip_tags(entry.get("content") or entry.get("summary") or "")


@ingest.register(FEED_KIND)
def parse_feed_job(db: Any, cfg: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Fetch a feed and queue its unread entries."""
    from .fetch import FetchError, fetch

    try:
        result = fetch(job["source"])
    except FetchError as exc:
        return {"status": ingest.FAILED, "error": str(exc)}

    try:
        entries = parse_feed(result.text, result.final_url)
    except ValueError as exc:
        return {"status": ingest.FAILED, "error": str(exc)}
    if not entries:
        return {
            "status": ingest.FAILED,
            "error": "no entries found — is that an RSS or Atom URL?",
        }

    source_key = f"feed:{result.final_url or job['source']}"
    imported = 0
    seen = 0
    failed: list[dict[str, str]] = []
    for entry in entries:
        # Keyed on `guid` where there is one: a URL changes when a title is
        # edited, and a feed re-serves the same entries forever.
        identity = entry.get("guid") or entry.get("link") or entry.get("title")
        if not identity:
            continue
        key = f"{source_key}#{identity}"
        if ingest.already_ingested(db, key, FEED_KIND):
            seen += 1
            continue
        try:
            _insert_feed_entry(db, entry, source_key, key)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("feed entry failed: %s", exc)
            failed.append({"entry": entry.get("title", ""), "error": str(exc)})

    return {
        "status": ingest.DONE,
        "detail": {
            "feed": result.final_url or job["source"],
            "found": len(entries),
            "imported": imported,
            "already_seen": seen,
            "failed": failed[:20],
            "failed_count": len(failed),
            "explains": "Each new entry becomes a note and joins the normal pipeline.",
        },
        "error": f"{len(failed)} entry(ies) failed" if failed else None,
    }


def _insert_feed_entry(db: Any, entry: dict[str, Any], feed: str, key: str) -> str:
    from ..db import new_id

    body = _summary_of(entry)
    title = entry.get("title") or (entry.get("link") or "Untitled")
    db.insert_note(
        {
            "id": new_id(),
            "title": title,
            "type": "text",
            "raw_text": body,
            "summary": body[:400],
            "status": "pending",
            "generated": 1,
            "source": {
                "url": entry.get("link", ""),
                "feed": feed,
                "published": entry.get("published", ""),
                "imported_from": "rss",
            },
        }
    )
    db.commit()
    ingest.mark_ingested(db, key, FEED_KIND, title)
    return title


# ---- #130: read later ------------------------------------------------------


class _ArticleExtractor(HTMLParser):
    """Readable text out of a page, best effort.

    Drops `script`, `style`, `nav`, `header`, `footer` and `aside` outright and
    counts `<p>` characters per block, keeping the densest run. That is the
    cheap 80%: it gets a usable article from most pages and a poor one from the
    rest, which is why `method` is reported.
    """

    DROP = {"script", "style", "nav", "header", "footer", "aside", "noscript", "form", "svg"}
    BLOCK = {"p", "div", "article", "section", "li", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._block: list[str] = []
        self._block_name = ""
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in self.DROP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK and not self._block_name:
            self._block_name = tag

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.DROP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == self._block_name:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self.title += data.strip()
            return
        if self._block_name:
            self._block.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", " ".join(self._block)).strip()
        if text:
            self.blocks.append(text)
        self._block = []
        self._block_name = ""

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush()


def extract_article(html: str) -> dict[str, Any]:
    """Readable text from a page. Returns `{"text", "title", "method"}`."""
    parser = _ArticleExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - malformed HTML is routine
        log.info("article extraction gave up: %s", exc)
    blocks = parser.blocks or []
    body = "\n\n".join(blocks).strip()
    title = parser.title or (blocks[0].split("\n")[0][:120] if blocks else "")
    method = "extracted" if len(body) >= MIN_ARTICLE_CHARS else "thin"
    if not body:
        method = "none"
    return {"text": body[:MAX_ARTICLE_CHARS], "title": title, "method": method}


@ingest.register(URL_KIND)
def parse_url_job(db: Any, cfg: Any, job: dict[str, Any]) -> dict[str, Any]:
    """Save a URL into the notes, with its text extracted."""
    from .fetch import FetchError, fetch

    try:
        result = fetch(job["source"])
    except FetchError as exc:
        return {"status": ingest.FAILED, "error": str(exc)}

    content_type = result.content_type
    if content_type and not content_type.startswith(("text/", "application/xhtml", "application/xml")):
        return {
            "status": ingest.FAILED,
            "error": f"that is a {content_type} file, not a page — use the PDF or audio importer",
        }

    article = extract_article(result.text)
    key = f"url:{result.final_url or job['source']}"
    if ingest.already_ingested(db, key, URL_KIND):
        return {"status": ingest.SKIPPED, "detail": {"already_saved": True}}

    from ..db import new_id

    title = article["title"] or result.final_url or job["source"]
    note_id = new_id()
    db.insert_note(
        {
            "id": note_id,
            "title": title,
            "type": "text",
            "raw_text": article["text"],
            "status": "pending",
            "generated": 1,
            "source": {"url": result.final_url or job["source"], "imported_from": "url"},
        }
    )
    db.commit()
    ingest.mark_ingested(db, key, URL_KIND, title)
    return {
        "status": ingest.DONE,
        "note_id": note_id,
        "detail": {
            "url": result.final_url or job["source"],
            "chars": len(article["text"]),
            "truncated": result.truncated,
            "method": article["method"],
            # Said plainly, because "here is your article" from a
            # navigation-scrape is a lie the user cannot detect.
            "explains": _METHOD_NOTES.get(article["method"], ""),
        },
    }


_METHOD_NOTES = {
    "extracted": "Readable text was extracted from the page.",
    "thin": (
        "Little readable text was found — this may be a page that renders in the "
        "browser, or a paywall. The link was kept anyway."
    ),
    "none": "No text could be extracted. The link was kept with its URL as the body.",
}