"""#460: a clear status for fully offline vs. any network feature in use.

The app calls itself local-first and did not say otherwise. The clearest single
piece of evidence that the claim was overstated is one line of CSS —

    @import url('https://fonts.googleapis.com/css2?family=Inter...')

— fetched on every page load, with no setting to turn it off. So this module's
first job is to be able to say "not fully offline" and name the reason.

The second job is to be precise about what "remote" means. Ollama on
127.0.0.1 is a socket and possibly a firewall prompt, not a phone home, and
reporting it as cloud traffic would be its own kind of dishonesty. Conversely a
provider on `192.168.x.x` *does* leave the machine, so the classifier checks the
address rather than the scheme — `is_private` is not the test.

Remote-ness is derived from the URL rather than from a list of known providers,
so pointing at a new host is reported without a code change and a private
address is not called cloud by accident.

The frontend reports its own half — the stylesheet fetch happens in the browser,
where this code cannot see it. `remote_stylesheets()` in `bulk.ts`'s sibling
`offline.ts` finds those at runtime rather than hardcoding them, so the number
goes down if and when the fonts are vendored.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from ..config import Config

log = logging.getLogger("fleeting.offline")

# Addresses that stay on this machine. Anything else — including a private LAN
# address — is traffic that leaves it.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def classify_url(url: str) -> str:
    """`"remote"` if a request to `url` leaves this machine, else `"none"`.

    An unparseable URL is treated as remote. A config typo should surface as
    "this might be leaving your machine, check it" rather than silently as
    "local".
    """
    raw = (url or "").strip()
    if not raw:
        return "none"
    try:
        host = (urlsplit(raw).hostname or "").lower()
    except ValueError:
        return "remote"
    if not host:
        return "remote"
    if host in _LOCAL_HOSTS:
        return "none"
    if host.endswith(".local") or host.endswith(".localhost"):
        return "none"
    return "remote"


def _feature(name: str, enabled: bool, network: str, detail: str) -> dict[str, Any]:
    return {"name": name, "enabled": enabled, "network": network, "detail": detail}


def _classify(cfg: Config) -> dict[str, Any]:
    """One entry per network-capable subsystem, in the order a person would ask
    about them."""
    features: list[dict[str, Any]] = []

    llm_on = (cfg.llm.provider or "none") != "none"
    llm_net = classify_url(cfg.llm.base_url) if llm_on else "none"
    features.append(
        _feature(
            "llm",
            llm_on,
            llm_net,
            (
                f"{cfg.llm.provider} at {cfg.llm.base_url or 'its default'}"
                if llm_on
                else "no model configured — enrichment uses heuristics instead"
            ),
        )
    )

    emb_provider = (cfg.llm.embedding_provider or "").strip() or (cfg.llm.provider or "none")
    emb_on = emb_provider != "none"
    emb_net = classify_url(cfg.llm.embedding_base_url) if emb_on else "none"
    features.append(
        _feature(
            "embeddings",
            emb_on,
            emb_net,
            (
                f"{emb_provider} at {cfg.llm.embedding_base_url}"
                if emb_on and cfg.llm.embedding_base_url
                else (emb_provider if emb_on else "not used — search is lexical")
            ),
        )
    )

    features.append(
        _feature(
            "transcription",
            bool(cfg.transcribe.model),
            "none",
            # Honest about the one-time fetch without making a local tool look
            # like it phones home on every dictation.
            f"'{cfg.transcribe.model}' runs locally; the model downloads once on first use",
        )
    )

    yt_on = (cfg.youtube.max_duration_min or 0) > 0
    features.append(
        _feature(
            "youtube",
            yt_on,
            "remote" if yt_on else "none",
            "yt-dlp fetches the video and audio over the network"
            if yt_on
            else "turned off — no URL is ever fetched",
        )
    )
    return {"features": features}


def report(cfg: Config) -> dict[str, Any]:
    """What this machine would reach for, and whether that leaves it.

    Never raises. A status page that 500s tells you nothing about your privacy,
    which is the one thing it exists to tell you.
    """
    try:
        result = _classify(cfg)
        features = result["features"]
    except Exception as exc:  # noqa: BLE001 - a report that fails is a report
        log.warning("offline report failed", exc_info=True)
        features = [
            _feature("report", True, "remote", f"could not determine: {type(exc).__name__}: {exc}")
        ]
    return {
        "offline": bool(features) and all(f["network"] == "none" for f in features),
        "features": features,
    }