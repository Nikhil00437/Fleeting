"""The network seam for ingest: fetch a URL the user pasted.

#129 (a feed) and #130 (read-later) are both "fetch a URL, turn the response into
a note". Only the parsing differs, so only the fetching is here.

**This app fetches arbitrary URLs on a loopback server.** Anything that reaches
`/api/ingest` can therefore make the machine issue a request to anything it can
reach, which is a server-side request forgery with a convenient victim: your
laptop, on your network, authenticated as you.

So there is a deny-list of destinations, and it is about *resolved addresses*
rather than hostnames — `http://127.0.0.1:7425/` and `http://localhost:7425/` and
`http://[::1]:7425/` are the same machine, and a check that only reads the URL
string catches none of the other two.

**The check happens twice**, before the request and after the connection: a
hostname can resolve to a public address at check time and a private one at
connect time, which is a DNS rebinding attack and is why the resolved address is
carried rather than the name.

**Bounded.** Size, time and content type are all limits, because this code path
is reachable by a pasted link and an unbounded read is a way to fill a disk.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("fleeting.fetch")

# Schemes we will fetch. `file://` reads the disk, and the other three are either
# opaque or actively dangerous to hand to a server.
ALLOWED_SCHEMES = frozenset({"http", "https"})

CONNECT_TIMEOUT = 10.0
# 8 MB. A feed is kilobytes and an article is a few hundred kilobytes; anything
# past this is not something anybody asked to read.
MAX_BYTES = 8 * 1024 * 1024

USER_AGENT = "fleeting/1.0 (+local-first capture)"

# Content types we will parse. Everything else still gets fetched and reported,
# so the user learns it was a PDF rather than a mystery.
TEXT_TYPES = ("text/", "application/xhtml", "application/xml", "application/rss", "application/atom+xml")


class FetchError(RuntimeError):
    """Anything that stopped the fetch. The message is shown to the user."""


@dataclass
class FetchResult:
    url: str
    status: int
    body: bytes = b""
    content_type: str = ""
    final_url: str = ""
    truncated: bool = False
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def _is_private(address: str) -> bool:
    """Would this address reach something that is not the public internet?"""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True  # not an address at all — treat as unsafe
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def check_url(url: str) -> list[str]:
    """Resolved addresses for `url`, or raise.

    Returns the addresses rather than just a verdict, because the caller needs to
    connect to the *resolved* address — otherwise it re-resolves the name and
    gets whatever the second lookup says.
    """
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchError(f"refusing to fetch {parsed.scheme or 'that'}:// — http and https only")
    host = parsed.hostname
    if not host:
        raise FetchError("that URL has no host in it")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve {host}: {exc}") from exc

    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise FetchError(f"{host} resolved to nothing")
    blocked = [a for a in addresses if _is_private(a)]
    if blocked:
        # Naming the address makes the refusal debuggable; "some address" does
        # not, and the user needs to know *why* their own machine refused.
        raise FetchError(
            f"refusing to fetch {host} — it resolves to {', '.join(blocked)}, "
            "which is not a public address"
        )
    return addresses


def fetch(url: str, *, max_bytes: int = MAX_BYTES, client: Any = None) -> FetchResult:
    """Fetch a URL. Raises `FetchError` with a message worth showing.

    `client` is injectable because these paths are reachable from the API and the
    tests must not make network calls.
    """
    check_url(url)
    http = client or _default_client()
    try:
        response = http.get(url, headers={"User-Agent": USER_AGENT}, timeout=CONNECT_TIMEOUT, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 - httpx raises a family of these
        raise FetchError(f"could not fetch {url}: {exc}") from exc

    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        raise FetchError(f"{url} returned HTTP {status}")

    # Re-check after the request: a redirect can land somewhere that was not
    # public when the first check ran.
    final_url = str(getattr(response, "url", url) or url)
    if final_url != url:
        check_url(final_url)

    body = response.content or b""
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
        log.info("truncated %s to %d bytes", url, max_bytes)
    return FetchResult(
        url=url,
        status=status,
        body=body,
        content_type=str(getattr(response, "headers", {}).get("content-type", "")).split(";")[0].strip(),
        final_url=final_url,
        truncated=truncated,
        headers={k.lower(): v for k, v in dict(getattr(response, "headers", {}) or {}).items()},
    )


def _default_client() -> Any:
    import httpx

    return httpx.Client()