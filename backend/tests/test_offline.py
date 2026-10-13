"""#460: a clear status for fully offline vs. any network feature in use.

This exists because the app claims to be local-first and did not say otherwise.
The clearest single piece of evidence that the claim was overstated is one line
of CSS:

    @import url('https://fonts.googleapis.com/css2?family=Inter...')

— fetched on every page load, unconditionally, with no setting to turn it off.
So the report has to be able to say "not fully offline" and name the reason, and
it has to distinguish a *local* network call from a remote one: Ollama on
127.0.0.1 is a socket and a firewall prompt, and treating it as cloud traffic
would be its own kind of dishonesty.

Remote origins are matched structurally rather than by a blocklist of known
hosts, so a provider pointing at a private address is not called "cloud" and a
new remote provider does not need a code change to be reported.
"""

from __future__ import annotations

import pytest

from fleeting.config import Config
from fleeting.services.offline import report


def cfg(**over) -> Config:
    c = Config()
    c.llm.provider = "none"
    c.llm.base_url = ""
    for k, v in over.items():
        section, _, field = k.partition("__")
        setattr(getattr(c, section), field, v)
    return c


def by_name(result) -> dict:
    return {f["name"]: f for f in result["features"]}


# ---- the headline ---------------------------------------------------------


def test_a_fully_local_setup_is_reported_offline() -> None:
    result = report(
        cfg(
            llm__provider="ollama",
            llm__base_url="http://127.0.0.1:11434",
            youtube__max_duration_min=0,
        )
    )
    assert result["offline"] is True
    assert all(f["network"] == "none" for f in result["features"])


def test_the_shipped_defaults_are_not_offline() -> None:
    """YouTube capture is on by default, so a fresh install reaches the network
    before the user does anything at all. That is a fact worth stating rather
    than discovering, and it is why the report exists."""
    default = Config()
    result = report(default)
    assert result["offline"] is False
    assert by_name(result)["youtube"]["network"] == "remote"


def test_a_remote_provider_is_not_reported_offline() -> None:
    result = report(cfg(llm__provider="custom", llm__base_url="https://api.example.com"))
    assert result["offline"] is False


def test_a_loopback_provider_is_not_cloud_traffic() -> None:
    """Ollama on localhost is a socket, not a phone home. Reporting it as remote
    would be its own kind of dishonesty."""
    for url in ("http://127.0.0.1:11434", "http://localhost:1234", "http://[::1]:8080"):
        result = report(cfg(llm__provider="custom", llm__base_url=url))
        assert by_name(result)["llm"]["network"] == "none", url


def test_a_lan_provider_is_reported_as_remote() -> None:
    """192.168.x.x leaves the machine. `is_private` is not the test."""
    result = report(cfg(llm__provider="custom", llm__base_url="http://192.168.1.50:11434"))
    assert by_name(result)["llm"]["network"] == "remote"


# ---- each feature ---------------------------------------------------------


def test_no_llm_configured_is_not_a_network_feature() -> None:
    out = by_name(report(cfg()))
    assert out["llm"]["network"] == "none"
    assert out["llm"]["enabled"] is False


def test_embeddings_are_reported_separately_from_the_llm() -> None:
    """They can point at different places, and conflating them hides the one
    that is actually leaving the machine."""
    result = report(
        cfg(
            llm__provider="ollama",
            llm__base_url="http://127.0.0.1:11434",
            llm__embedding_provider="custom",
            llm__embedding_base_url="https://api.openai.com",
        )
    )
    out = by_name(result)
    assert out["llm"]["network"] == "none"
    assert out["embeddings"]["network"] == "remote"
    assert result["offline"] is False


def test_the_whisper_model_is_local_after_it_is_downloaded() -> None:
    """A one-time fetch from the hub, then it is on disk forever. Saying
    'downloads a model' with no qualification makes a local tool look like it
    phones home on every dictation."""
    out = by_name(report(cfg(transcribe__model="base")))
    assert out["transcription"]["network"] == "none"
    assert "first" in out["transcription"]["detail"].lower()


def test_youtube_is_reported_as_network_when_captures_can_use_it() -> None:
    out = by_name(report(cfg(youtube__transcribe_fallback=True)))
    assert out["youtube"]["network"] == "remote"


def test_youtube_is_off_when_the_feature_is_turned_off() -> None:
    out = by_name(report(cfg(youtube__max_duration_min=0)))
    assert out["youtube"]["network"] == "none"


# ---- shape ----------------------------------------------------------------


def test_every_feature_names_itself_and_where_it_goes() -> None:
    """A feature with no detail is a feature nobody can act on."""
    for f in report(cfg()).get("features", []):
        assert f["name"] and f["detail"]


def test_the_report_is_serialisable() -> None:
    """It goes over the API; a Path in there is a 500."""
    import json

    json.dumps(report(cfg()))


def test_a_malformed_base_url_does_not_break_the_report() -> None:
    """Hand-edited config is a real thing."""
    result = report(cfg(llm__provider="custom", llm__base_url="not a url at all"))
    assert by_name(result)["llm"]["network"] == "remote"


def test_a_probe_that_raises_does_not_take_the_page_down() -> None:
    from fleeting.services import offline

    def boom(*a, **k):
        raise OSError("no network stack")

    real = offline._classify
    try:
        offline._classify = boom
        result = offline.report(cfg())
    finally:
        offline._classify = real
    assert result["features"]
    assert result["offline"] is False


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.example.com", "remote"),
        ("http://example.com", "remote"),
        ("http://127.0.0.1:11434", "none"),
        ("http://localhost:1234", "none"),
        ("http://[::1]:8080", "none"),
        ("http://192.168.1.5:8080", "remote"),
        ("http://10.0.0.3", "remote"),
        ("", "none"),
        # `urlsplit("garbage")` does not raise — it parses as a path with no
        # hostname, which the `not host` branch catches. A malformed IPv6 URL is
        # the input that actually reaches the `except`, and without it that
        # branch was dead code a mutation could not detect.
        ("garbage", "remote"),
        ("http://[::1", "remote"),
        ("http://[fe80::1", "remote"),
    ],
)
def test_the_classifier(url: str, expected: str) -> None:
    from fleeting.services.offline import classify_url

    assert classify_url(url) == expected

def test_the_endpoint_answers(client) -> None:
    body = client.get("/api/offline").json()
    assert set(body) == {"offline", "features"}
    assert body["features"]
