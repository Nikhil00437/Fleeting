"""#141: a network-egress self-check, as distinct from a configuration report.

`GET /api/offline` (#460) answers *"what is configured to reach the network?"* by
reading the config. This answers the harder question: **is anything actually
there?** A config report can be confidently wrong — a feature set to a local URL
whose binary phones home regardless, a stale base_url pointing at a host that is
still up, a provider endpoint that changed its behaviour after you configured it.

So this opens a real TCP connection to each configured remote endpoint and reports
whether something answered. That is the difference between a self-check and a
read of your own settings file.

**What it sends: nothing.** A TCP connect and a close. No request, no headers, no
payload. The remote host does see a connection from your machine, which is worth
saying plainly — a "does this leave the house?" tool that itself makes an outbound
connection is a poor joke, and the cost is the same one the app already pays
whenever that feature runs.

**Bounded and parallel.** Every connect has a short timeout and they run at once,
so a firewall that blackholes packets cannot turn a status page into a 20-second
hang. A status page that times out is indistinguishable from a status page that is
broken.

Results are **not cached**. A cached answer to "can I reach the network right
now" is a lie the moment conditions change, and this is called rarely enough that
caching would buy nothing.
"""

from __future__ import annotations

import logging
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

from ..config import Config
from .offline import report

log = logging.getLogger("fleeting.egress")

# Short on purpose. A host that blackholes rather than refuses is the interesting
# case, and the answer for both is "not reachable from here" — waiting longer to
# be sure would only make the page hang.
CONNECT_TIMEOUT = 2.0

# Every check at once: the wall-clock cost is the slowest one, not the sum.
MAX_WORKERS = 8


def _target(url: str) -> tuple[str, int] | None:
    """`(host, port)` for a configured base URL, or None if it is unusable."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or (443 if parsed.scheme in ("https", "wss") else 80)


def _probe(url: str) -> dict[str, Any]:
    """Can something be reached at this URL? Never raises."""
    target = _target(url)
    if target is None:
        return {"url": url, "reachable": None, "detail": "not a usable URL"}
    host, port = target
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return {"url": url, "reachable": True, "detail": f"{host}:{port} answered"}
    except (OSError, socket.timeout) as exc:
        return {
            "url": url,
            "reachable": False,
            "detail": f"{host}:{port} did not answer ({type(exc).__name__})",
        }
    except Exception as exc:  # noqa: BLE001 - a self-check that fails is a result
        return {"url": url, "reachable": False, "detail": f"probe failed: {exc}"}


def _urls(cfg: Config) -> list[str]:
    """Every configured endpoint, deduplicated.

    Several features can share one provider, and probing it three times would
    make the check slower for no extra information.
    """
    seen: list[str] = []
    for url in (
        getattr(cfg.llm, "base_url", ""),
        # Embeddings are a separate egress path with their own base URL. Leaving
        # it out would report "no network" for a machine that is in fact sending
        # every capture to a remote embedding endpoint.
        getattr(cfg.llm, "embedding_base_url", ""),
    ):
        if url and url not in seen:
            seen.append(url)
    return seen


def self_check(cfg: Config) -> dict[str, Any]:
    """Configuration report plus a live reachability probe of each endpoint."""
    # Never raises. A privacy status page that 500s tells you nothing about your
    # privacy, which is the one thing it exists to tell you — so a broken config
    # report degrades to "cannot tell" rather than taking the page down with it.
    try:
        report_body = report(cfg)
    except Exception as exc:  # noqa: BLE001
        log.warning("offline report failed", exc_info=True)
        return {
            "configured_remote": [],
            "offline": False,
            "probed": [],
            "reachable": [],
            "sends": "a TCP connection and nothing else — no request, no payload",
            "detail": f"could not determine egress: {type(exc).__name__}: {exc}",
        }
    urls = _urls(cfg)
    if urls:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(urls))) as pool:
            probes = list(pool.map(_probe, urls))
    else:
        probes = []

    reachable = [p for p in probes if p["reachable"] is True]
    return {
        # The config report is still the headline: nothing is configured to reach
        # out, which is the strongest statement available. The probe can only
        # confirm what is already configured, never find an unknown egress.
        "configured_remote": [f["name"] for f in report_body["features"] if f["network"] == "remote"],
        "offline": report_body["offline"],
        "probed": probes,
        "reachable": [p["url"] for p in reachable],
        "sends": "a TCP connection and nothing else — no request, no payload",
        "detail": (
            "Nothing was probed: no remote endpoint is configured."
            if not urls
            else f"Probed {len(urls)} endpoint(s); {len(reachable)} answered."
        ),
    }