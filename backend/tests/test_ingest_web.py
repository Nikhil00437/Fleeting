"""#129 feeds, #130 read-later, and the fetch seam underneath both.

The fetch tests matter as much as the parsing ones. This app fetches arbitrary
URLs on a loopback server, so anything that reaches `/api/ingest` can make the
machine issue a request to anything it can reach. That is SSRF with a convenient
victim: your laptop, on your network, authenticated as you.

So:

1. **The destination check is about resolved addresses, not hostnames.**
   `127.0.0.1:7425`, `localhost:7425` and `[::1]:7425` are one machine, and a
   check that only reads the URL string catches neither of the other two.
2. **It runs again after the request.** A redirect can land somewhere that was
   not public when the first check ran — DNS rebinding, and the reason the
   resolved address is carried rather than the name.
3. **`file://` is refused.** It reads the disk, on a server reachable by
   anything local.
4. **Bounded.** Size, time, schemes. This path is reachable by a pasted link.

Then the parsers: a feed re-serves the same entries forever, so seen-ness is keyed
on `guid` rather than URL (a URL changes when a title is edited), and article
extraction reports *how well it did* because "here is your article" from a
navigation scrape is a lie the user cannot detect.
"""

from __future__ import annotations

import pytest

from fleeting.services import fetch, ingest, ingest_web

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>A feed</title>
  <item>
    <title>First entry</title>
    <link>https://example.com/1</link>
    <guid>guid-1</guid>
    <pubDate>Mon, 05 Jan 2026 10:00:00 +0000</pubDate>
    <description>&lt;p&gt;Hello &lt;b&gt;there&lt;/b&gt;&lt;/p&gt;</description>
  </item>
  <item>
    <title>Second entry</title>
    <link>https://example.com/2</link>
    <guid>guid-2</guid>
  </item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>An atom feed</title>
  <entry>
    <title>Atom entry</title>
    <link href="https://example.com/a1"/>
    <id>urn:uuid:abc</id>
    <updated>2026-01-05T10:00:00Z</updated>
    <summary>Some text</summary>
  </entry>
</feed>"""

ARTICLE = (
    "<html><head><title>The Article</title>"
    "<script>var tracking = 1;</script><style>p{color:red}</style></head>"
    "<body><nav>Home About Contact</nav>"
    "<article><p>" + ("Real content here. " * 60) + "</p>"
    "<p>More of it.</p></article>"
    "<footer>copyright</footer></body></html>"
)


@pytest.fixture()
def db(tmp_path):
    from fleeting.db import Database

    database = Database(str(tmp_path / "w.db"))
    database.migrate()
    return database


@pytest.fixture()
def cfg(tmp_path):
    from fleeting.config import PathsConfig

    return PathsConfig(vault_dir=str(tmp_path / "vault"))


def stub_fetch(monkeypatch, body: str, content_type: str = "text/html", final: str = "https://example.com/"):
    """Replace the network with a canned response."""
    calls: list[str] = []

    class Resp:
        status_code = 200
        content = body.encode("utf-8")
        headers = {"content-type": content_type}
        url = final

    def fake(url, **kw):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(fetch, "_default_client", lambda: type("C", (), {"get": staticmethod(fake)})())
    monkeypatch.setattr(fetch, "check_url", lambda u: ["93.184.216.34"])
    return calls


# ---- the network seam ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:7425/api/notes",
        "http://localhost/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "ftp://example.com/",
    ],
)
def test_a_non_public_destination_is_refused(url) -> None:
    """Any local process can reach /api/ingest, so any local process could
    otherwise make this machine fetch anything it can reach."""
    with pytest.raises(fetch.FetchError):
        fetch.check_url(url)


def test_the_refusal_names_the_address() -> None:
    """"some address" is not debuggable; the user needs to know why their own
    machine refused."""
    with pytest.raises(fetch.FetchError) as err:
        fetch.check_url("http://127.0.0.1:7425/")
    assert "127.0.0.1" in str(err.value)


def test_a_public_address_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    assert fetch.check_url("https://example.com/feed") == ["93.184.216.34"]


def test_a_redirect_is_rechecked(monkeypatch) -> None:
    """A redirect can land somewhere that was not public when the first check
    ran. This is DNS rebinding, and it is why the resolved address is carried
    rather than the name."""
    checked: list[str] = []
    monkeypatch.setattr(fetch, "check_url", lambda u: checked.append(u) or ["93.184.216.34"])

    class Resp:
        status_code = 200
        content = b"hi"
        headers = {"content-type": "text/plain"}
        url = "https://elsewhere.example/"

    monkeypatch.setattr(fetch, "_default_client", lambda: type("C", (), {"get": staticmethod(lambda *a, **k: Resp())})())
    fetch.fetch("https://example.com/")
    assert checked == ["https://example.com/", "https://elsewhere.example/"]


def test_an_http_error_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "check_url", lambda u: ["93.184.216.34"])

    class Resp:
        status_code = 404
        content = b""
        headers = {}

    monkeypatch.setattr(fetch, "_default_client", lambda: type("C", (), {"get": staticmethod(lambda *a, **k: Resp())})())
    with pytest.raises(fetch.FetchError) as err:
        fetch.fetch("https://example.com/x")
    assert "404" in str(err.value)


def test_a_large_response_is_truncated(monkeypatch) -> None:
    monkeypatch.setattr(fetch, "check_url", lambda u: ["93.184.216.34"])

    class Resp:
        status_code = 200
        content = b"x" * 5000
        headers = {"content-type": "text/plain"}
        url = "https://example.com/"

    monkeypatch.setattr(fetch, "_default_client", lambda: type("C", (), {"get": staticmethod(lambda *a, **k: Resp())})())
    result = fetch.fetch("https://example.com/", max_bytes=1000)
    assert len(result.body) == 1000
    assert result.truncated is True


def test_only_a_few_schemes_are_allowed() -> None:
    assert fetch.ALLOWED_SCHEMES == frozenset({"http", "https"})


# ---- #129: feeds -----------------------------------------------------------


def test_an_rss_feed_parses() -> None:
    entries = ingest_web.parse_feed(RSS)
    assert [e["title"] for e in entries] == ["First entry", "Second entry"]


def test_an_atom_feed_parses_too() -> None:
    """A feed that declares `atom:` and one that does not should not need two
    parsers."""
    entries = ingest_web.parse_feed(ATOM)
    assert entries[0]["title"] == "Atom entry"
    assert entries[0]["link"] == "https://example.com/a1"


def test_the_guid_is_kept() -> None:
    """A feed re-serves the same entries forever, and a URL changes when a title
    is edited. `guid` is what the publisher says identifies the entry."""
    assert ingest_web.parse_feed(RSS)[0]["guid"] == "guid-1"


def test_the_published_date_is_kept() -> None:
    assert "2026" in ingest_web.parse_feed(RSS)[0]["published"]


def test_malformed_xml_is_refused() -> None:
    # Not "<html>not a feed</html>" — that is well-formed XML which simply is
    # not a feed, and it is handled a few lines below this one by the job.
    with pytest.raises(ValueError):
        ingest_web.parse_feed("<rss><channel><title>unclosed")


def test_well_formed_non_feed_xml_yields_no_entries() -> None:
    assert ingest_web.parse_feed("<html><body>nope</body></html>") == []


def test_a_feed_is_capped() -> None:
    """A feed is not an archive, and a 2,000-entry backfill is nobody's idea of a
    subscription."""
    big = "<rss><channel>" + "".join(
        f"<item><title>n{i}</title><guid>g{i}</guid></item>" for i in range(500)
    ) + "</channel></rss>"
    assert len(ingest_web.parse_feed(big)) == ingest_web.MAX_ENTRIES


def test_entries_become_pending_notes(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, RSS, "application/rss+xml")
    job = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed.xml")
    assert ingest.run_one(db, cfg, job["id"])["status"] == ingest.DONE
    assert len(db.list_notes(limit=10)) == 2


def test_feed_notes_join_the_pipeline(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, RSS, "application/rss+xml")
    job = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed.xml")
    ingest.run_one(db, cfg, job["id"])
    assert all(n["status"] == "pending" for n in db.list_notes(limit=10))


def test_feed_html_is_stripped_to_text(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, RSS, "application/rss+xml")
    job = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed.xml")
    ingest.run_one(db, cfg, job["id"])
    note = db.list_notes(limit=10)[0]
    assert "<p>" not in note["raw_text"]
    assert "Hello there" in note["raw_text"]


def test_a_refetched_feed_imports_nothing_new(db, cfg, monkeypatch) -> None:
    """Feeds re-serve the same entries forever."""
    stub_fetch(monkeypatch, RSS, "application/rss+xml")
    first = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed.xml")
    ingest.run_one(db, cfg, first["id"])
    second = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed.xml")
    done = ingest.run_one(db, cfg, second["id"])
    assert done["detail"]["imported"] == 0
    assert done["detail"]["already_seen"] == 2


def test_a_feed_of_html_is_refused_clearly(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, "<html><body>nope</body></html>")
    job = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/")
    assert "no entries" in ingest.run_one(db, cfg, job["id"])["error"]


def test_an_empty_feed_is_refused_clearly(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, "<rss><channel><title>x</title></channel></rss>")
    job = ingest.enqueue(db, ingest_web.FEED_KIND, "https://example.com/feed")
    assert ingest.run_one(db, cfg, job["id"])["status"] == ingest.FAILED


# ---- #130: read later ------------------------------------------------------


def test_article_text_is_extracted() -> None:
    article = ingest_web.extract_article(ARTICLE)
    assert "Real content" in article["text"]
    assert article["method"] == "extracted"


def test_scripts_and_navigation_are_dropped() -> None:
    text = ingest_web.extract_article(ARTICLE)["text"]
    assert "tracking" not in text
    assert "Home About Contact" not in text


def test_a_script_nested_inside_a_block_is_dropped() -> None:
    """The case the skip guard actually exists for.

    `<script>` at the top level is dropped anyway, because it is not a block
    element and block text is the only thing collected. A script *inside* a
    `<div>` — which is how most tracking and widget scripts ship — would
    otherwise be collected as prose.
    """
    html = "<html><body><div>" + ("Real words. " * 60) + "<script>track_me();</script></div></body></html>"
    text = ingest_web.extract_article(html)["text"]
    assert "Real words" in text
    assert "track_me" not in text


def test_a_style_inside_a_block_is_dropped() -> None:
    html = "<html><body><div>" + ("Real words. " * 60) + "<style>p{color:red}</style></div></body></html>"
    assert "color:red" not in ingest_web.extract_article(html)["text"]


def test_the_title_is_taken_from_the_page() -> None:
    assert ingest_web.extract_article(ARTICLE)["title"] == "The Article"


def test_a_thin_page_says_so() -> None:
    """"Here is your article" from a navigation scrape is a lie the user cannot
    detect."""
    thin = ingest_web.extract_article("<html><body><div>menu</div></body></html>")
    assert thin["method"] == "thin"
    assert "renders in the browser" in _notes_for(thin)


def test_an_empty_page_says_so() -> None:
    assert ingest_web.extract_article("<html><body></body></html>")["method"] == "none"


def _notes_for(article: dict) -> str:
    return ingest_web._METHOD_NOTES.get(article["method"], "")


def test_a_url_becomes_a_note_with_its_text(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, ARTICLE)
    job = ingest.enqueue(db, ingest_web.URL_KIND, "https://example.com/post")
    done = ingest.run_one(db, cfg, job["id"])
    assert done["status"] == ingest.DONE
    note = db.get_note(done["note_id"])
    assert "Real content" in note["raw_text"]
    assert note["source"]["url"] == "https://example.com/"


def test_saving_the_same_url_twice_is_skipped(db, cfg, monkeypatch) -> None:
    """A link that dies is a link you cannot read, so saving twice would be two
    copies of the same dead article."""
    stub_fetch(monkeypatch, ARTICLE)
    first = ingest.enqueue(db, ingest_web.URL_KIND, "https://example.com/post")
    ingest.run_one(db, cfg, first["id"])
    second = ingest.enqueue(db, ingest_web.URL_KIND, "https://example.com/post")
    assert ingest.run_one(db, cfg, second["id"])["status"] == ingest.SKIPPED


def test_a_pdf_url_is_refused_with_a_pointer(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, "%PDF-1.4", "application/pdf")
    job = ingest.enqueue(db, ingest_web.URL_KIND, "https://example.com/doc.pdf")
    assert "PDF" in ingest.run_one(db, cfg, job["id"])["error"]


def test_the_result_reports_how_well_it_did(db, cfg, monkeypatch) -> None:
    stub_fetch(monkeypatch, ARTICLE)
    job = ingest.enqueue(db, ingest_web.URL_KIND, "https://example.com/post")
    done = ingest.run_one(db, cfg, job["id"])
    assert done["detail"]["method"] == "extracted"
    assert done["detail"]["explains"]


def test_a_fetch_failure_is_recorded(db, cfg, monkeypatch) -> None:
    monkeypatch.setattr(fetch, "fetch", lambda url, **kw: (_ for _ in ()).throw(fetch.FetchError("refused")))
    job = ingest.enqueue(db, ingest_web.URL_KIND, "http://127.0.0.1/")
    done = ingest.run_one(db, cfg, job["id"])
    assert done["status"] == ingest.FAILED
    assert "refused" in done["error"]


# ---- the endpoints ---------------------------------------------------------


def test_a_feed_can_be_queued_through_the_api(client, monkeypatch) -> None:
    stub_fetch(monkeypatch, RSS, "application/rss+xml")
    r = client.post("/api/ingest", json={"kind": "rss", "source": "https://example.com/feed.xml"})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    client.post(f"/api/ingest/jobs/{job_id}/run")
    assert len(client.app.state.st.db.list_notes(limit=10)) == 2


def test_read_later_through_the_api(client, monkeypatch) -> None:
    stub_fetch(monkeypatch, ARTICLE)
    job = client.post("/api/ingest", json={"kind": "url", "source": "https://example.com/post"}).json()
    done = client.post(f"/api/ingest/jobs/{job['id']}/run").json()
    assert done["status"] == "done"
    assert client.app.state.st.db.get_note(done["note_id"]) is not None


def test_the_preview_only_supports_shipped_parsers(client) -> None:
    r = client.post("/api/ingest/preview", json={"kind": "rss", "source": "https://x"})
    assert r.status_code == 400
    assert "markdown-folder" in r.json()["detail"]["supported"]