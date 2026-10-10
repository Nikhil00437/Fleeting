"""Settings read/write + connection tests."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..activity import session_idle_probe
from ..config import CONFIG_PATH, LLMConfig, expand_path, save_config
from ..models import LLMProbeIn, SettingsIn
from ..models import ReprocessIn
from ..services import health as health_svc
from ..services import llm
from ..services.reprocess import reprocess_corpus, validate_reprocess

log = logging.getLogger("fleeting.settings")


def _idle_hint_readable() -> bool:
    """#60 whether logind actually answers on this host."""
    return session_idle_probe()


router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_payload(request: Request) -> dict:
    st = request.app.state.st
    cfg = st.cfg
    return {
        "host": cfg.server.host,
        "port": cfg.server.port,
        "vault_dir": cfg.paths.vault_dir,
        "vault_sync": cfg.paths.vault_sync,
        "vault_writable": _check_vault_writable(cfg.paths.vault_dir),
        "llm_provider": cfg.llm.provider,
        "llm_base_url": cfg.llm.base_url,
        "llm_model": cfg.llm.model,
        "llm_timeout_secs": cfg.llm.timeout_secs,
        "llm_api_key_set": bool(cfg.llm.api_key),
        # #257/#416/#451: same idea as the llm_* block — the section's own
        # fields, flattened so the settings UI reads one shape.
        "llm_fallback_models": cfg.llm.fallback_models,
        "llm_preferred_tags": cfg.llm.preferred_tags,
        # Separate from llm_model on purpose: asking a chat model for
        # embeddings returns nothing usable and silently degrades the index.
        "llm_embedding_model": cfg.llm.embedding_model,
        # Empty means "same server as chat". Set when the embedder runs
        # somewhere else, e.g. LM Studio while Ollama serves chat.
        "llm_embedding_base_url": cfg.llm.embedding_base_url,
        "llm_embedding_provider": cfg.llm.embedding_provider,
        # #92: role overrides, empty meaning "use the model above".
        "llm_enrich_model": cfg.llm.enrich_model,
        "llm_report_model": cfg.llm.report_model,
        "llm_assistant_model": cfg.llm.assistant_model,
        "entities_stale_days": cfg.entities.stale_days,
        "writing_style_guide": cfg.writing.style_guide,
        "transcribe_model": cfg.transcribe.model,
        "transcribe_language": cfg.transcribe.language,
        "transcribe_vocabulary": cfg.transcribe.vocabulary,
        "transcribe_translate": cfg.transcribe.translate,
        "transcribe_cleanup_audio": cfg.transcribe.cleanup_audio,
        "transcribe_keep_audio": cfg.transcribe.keep_audio,
        "transcribe_voice_punctuation": cfg.transcribe.voice_punctuation,
        "transcribe_auto_format": cfg.transcribe.auto_format,
        "transcribe_replacements": cfg.transcribe.replacements,
        "transcribe_diarize": cfg.transcribe.diarize,
        "transcribe_hf_token_set": bool(cfg.transcribe.hf_token),
        "transcribe_loaded": st.transcriber.is_ready(),
        "transcribe_cached_models": st.transcriber.cached_models(),
        "transcribe_progress": st.transcriber.progress,
        "yt_transcribe_fallback": cfg.youtube.transcribe_fallback,
        "yt_max_duration_min": cfg.youtube.max_duration_min,
        "desktop_notifications": cfg.notifications.desktop,
        # #110: the nightly "what did I forget?" for open loops. Opt-in.
        "notifications_nightly_nudge": cfg.notifications.nightly_nudge,
        "activity_enabled": cfg.activity.enabled,
        "activity_paused": st.activity.is_paused() if st.activity else False,
        "activity_poll_secs": cfg.activity.poll_secs,
        "activity_idle_after_min": cfg.activity.idle_after_min,
        # #60 which idle signal the collector is using, and whether the
        # session manager's answer is actually readable on this host.
        "activity_idle_source": cfg.activity.idle_source,
        "activity_idle_available": _idle_hint_readable(),
        "activity_excluded_apps": cfg.activity.excluded_apps,
        "activity_auto_daily_log": cfg.activity.auto_daily_log,
        "activity_watch_dirs": cfg.activity.watch_dirs,
        "activity_mirror_daily_log": cfg.activity.mirror_daily_log,
        "activity_auto_weekly_log": cfg.activity.auto_weekly_log,
        "activity_retention_days": cfg.activity.retention_days,
        "activity_running": bool(st.activity and st.activity.running),
        "config_path": str(CONFIG_PATH),
    }


def _check_vault_writable(vault_dir: str) -> bool:
    try:
        vault = expand_path(vault_dir)
        vault.mkdir(parents=True, exist_ok=True)
        probe = vault / ".fleeting-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@router.get("")
def get_settings(request: Request) -> dict:
    return _settings_payload(request)


@router.put("")
async def update_settings(body: SettingsIn, request: Request) -> dict:
    st = request.app.state.st
    cfg = st.cfg
    if body.host is not None:
        cfg.server.host = body.host.strip() or cfg.server.host
    if body.port is not None:
        cfg.server.port = body.port
    if body.vault_dir is not None:
        if not body.vault_dir.strip():
            raise HTTPException(422, "vault dir cannot be empty")
        cfg.paths.vault_dir = body.vault_dir.strip()
        if not _check_vault_writable(cfg.paths.vault_dir):
            raise HTTPException(422, "vault directory is not writable")
    if body.vault_sync is not None:
        cfg.paths.vault_sync = body.vault_sync
    if body.llm_provider is not None:
        cfg.llm.provider = body.llm_provider
    if body.llm_base_url is not None:
        cfg.llm.base_url = body.llm_base_url.strip() or cfg.llm.base_url
    if body.llm_model is not None:
        cfg.llm.model = body.llm_model.strip()
    if body.llm_timeout_secs is not None:
        cfg.llm.timeout_secs = body.llm_timeout_secs
    if body.llm_fallback_models is not None:
        cfg.llm.fallback_models = body.llm_fallback_models.strip()
    if body.llm_preferred_tags is not None:
        cfg.llm.preferred_tags = body.llm_preferred_tags.strip()
    if body.llm_embedding_model is not None:
        cfg.llm.embedding_model = body.llm_embedding_model.strip()
    if body.llm_embedding_base_url is not None:
        cfg.llm.embedding_base_url = body.llm_embedding_base_url.strip()
    if body.llm_embedding_provider is not None:
        cfg.llm.embedding_provider = body.llm_embedding_provider.strip()
    for field in ("enrich_model", "report_model", "assistant_model"):
        value = getattr(body, f"llm_{field}", None)
        if value is not None:
            setattr(cfg.llm, field, value.strip())
    if body.entities_stale_days is not None:
        cfg.entities.stale_days = body.entities_stale_days
    if body.writing_style_guide is not None:
        cfg.writing.style_guide = body.writing_style_guide
    if body.llm_api_key is not None:
        # Never echoed back by GET, so an absent value must mean "unchanged"
        # rather than "wipe it".
        cfg.llm.api_key = body.llm_api_key.strip()
    if body.transcribe_model is not None:
        if body.transcribe_model != cfg.transcribe.model:
            cfg.transcribe.model = body.transcribe_model
            st.transcriber.set_model(body.transcribe_model)
    if body.transcribe_language is not None:
        cfg.transcribe.language = body.transcribe_language.strip().lower() or "auto"
    if body.transcribe_vocabulary is not None:
        cfg.transcribe.vocabulary = body.transcribe_vocabulary.strip()
    if body.transcribe_translate is not None:
        cfg.transcribe.translate = body.transcribe_translate
    if body.transcribe_cleanup_audio is not None:
        cfg.transcribe.cleanup_audio = body.transcribe_cleanup_audio
    if body.transcribe_keep_audio is not None:
        cfg.transcribe.keep_audio = body.transcribe_keep_audio
    if body.transcribe_voice_punctuation is not None:
        cfg.transcribe.voice_punctuation = body.transcribe_voice_punctuation
    if body.transcribe_auto_format is not None:
        cfg.transcribe.auto_format = body.transcribe_auto_format
    if body.transcribe_replacements is not None:
        cfg.transcribe.replacements = body.transcribe_replacements.strip()
    if body.transcribe_diarize is not None:
        cfg.transcribe.diarize = body.transcribe_diarize
    if body.transcribe_hf_token is not None:
        # Never returned by GET (only `hf_token_set`), so an explicit "" clears it.
        cfg.transcribe.hf_token = body.transcribe_hf_token.strip()
    if body.yt_transcribe_fallback is not None:
        cfg.youtube.transcribe_fallback = body.yt_transcribe_fallback
    if body.yt_max_duration_min is not None:
        cfg.youtube.max_duration_min = body.yt_max_duration_min
    if body.desktop_notifications is not None:
        cfg.notifications.desktop = body.desktop_notifications
    if body.notifications_nightly_nudge is not None:
        cfg.notifications.nightly_nudge = body.notifications_nightly_nudge
    if body.activity_enabled is not None:
        cfg.activity.enabled = body.activity_enabled
    if body.activity_poll_secs is not None:
        cfg.activity.poll_secs = max(5, body.activity_poll_secs)
    if body.activity_idle_after_min is not None:
        cfg.activity.idle_after_min = max(1, body.activity_idle_after_min)
    if body.activity_idle_source is not None:
        cfg.activity.idle_source = body.activity_idle_source
    if body.activity_excluded_apps is not None:
        cfg.activity.excluded_apps = body.activity_excluded_apps.strip()
    if body.activity_auto_daily_log is not None:
        cfg.activity.auto_daily_log = body.activity_auto_daily_log
    if body.activity_watch_dirs is not None:
        cfg.activity.watch_dirs = body.activity_watch_dirs.strip()
    if body.activity_mirror_daily_log is not None:
        cfg.activity.mirror_daily_log = body.activity_mirror_daily_log
    if body.activity_auto_weekly_log is not None:
        cfg.activity.auto_weekly_log = body.activity_auto_weekly_log
    if body.activity_retention_days is not None:
        cfg.activity.retention_days = body.activity_retention_days

    save_config(cfg)
    return _settings_payload(request)


@router.post("/test-llm")
async def test_llm(request: Request, body: LLMProbeIn | None = None) -> dict:
    """Probe the LLM endpoint and return its chat-capable models.

    Accepts optional overrides so the UI can test a URL the user just typed
    without saving first — otherwise the probe races the settings PUT.
    """
    st = request.app.state.st
    cfg = st.cfg.llm
    probe = LLMConfig(
        provider=cfg.provider,
        base_url=cfg.base_url,
        model=cfg.model,
        timeout_secs=cfg.timeout_secs,
    )
    if body is not None:
        if body.provider is not None:
            probe.provider = body.provider
        if body.base_url is not None:
            probe.base_url = body.base_url.strip()
        if body.model is not None:
            probe.model = body.model.strip()
        if body.api_key is not None:
            probe.api_key = body.api_key.strip()
    return await llm.check_llm(probe)


# #94 lives at the app root, not under /api/settings: it is a read of app
# health, and burying it among settings hides the one page you want when
# something is actually wrong.
health_router = APIRouter(prefix="/api", tags=["health"])


@health_router.get("/health-panel")
def health_panel(request: Request) -> dict:
    """#94 latency, queue depth and embedding status in one read.

    Assembled from things that are already recorded rather than from a fresh
    probe, so opening the panel costs nothing. `/health-panel/retry` is the
    explicit "try again" when something is actually down.
    """
    st = request.app.state.st
    return {
        "llm": health_svc.llm_health(st.db),
        "embeddings": health_svc.embedding_status(
            st.db, st.db.kv_get("embedding_model_used")
        ),
        "queue": health_svc.queue_status(getattr(st, "processor", None)),
    }


@health_router.post("/health-panel/retry")
async def health_panel_retry(request: Request) -> dict:
    """#94 one-click retry: re-probe the provider and return the fresh answer.

    Always 200. A failure here *is* the answer, not an error — raising would
    turn the retry button into a second thing that appears broken.
    """
    return await test_llm(request, None)


@router.post("/test-whisper")
async def test_whisper(request: Request) -> dict:
    """Load the configured whisper model with a 1s silent wav."""
    import asyncio
    import struct
    import wave

    st = request.app.state.st
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "probe.wav"
        with wave.open(str(wav), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(struct.pack("<" + "h" * 16000, *([0] * 16000)))
        try:
            await asyncio.to_thread(st.transcriber.transcribe_wav, wav)
        except Exception as exc:
            raise HTTPException(502, f"whisper failed to load: {exc}")
    return {
        "ok": True,
        "model": st.transcriber.loaded_model_size or st.cfg.transcribe.model,
    }


@router.post("/vault/resync")
def resync_vault(request: Request) -> dict:
    st = request.app.state.st
    if st.vault_watcher is not None and hasattr(st.vault_watcher, "resync_all"):
        return st.vault_watcher.resync_all()
    from ..services.vault_watcher import resync_all

    vault_dir = expand_path(st.cfg.paths.vault_dir)
    return resync_all(vault_dir, st.db, st.bus, st.cfg)



def backfill_embeddings_stream(db, cfg, bus) -> dict:
    """Re-embed every note left on an older model, reporting progress.

    Switching the LLM on changes the embedding dimensionality, and vectors of
    different lengths cannot be compared — so every note captured before the
    switch becomes invisible to semantic search until it is redone. This is the
    migration that makes turning the model on safe.

    Synchronous; the caller runs it in a thread and owns cancellation.
    Progress is published per note because a large corpus is one HTTP call per
    note and the UI has to see it moving.
    """
    from ..routers.system import _embedding_status
    from ..services.embeddings import backfill_embeddings

    if cfg.llm.provider == "none":
        return {"migrated": 0, "skipped": "no llm configured"}

    class _St:
        pass

    st = _St()
    st.cfg = cfg
    st.db = db
    model, stale_before = _embedding_status(st)
    if stale_before == 0:
        return {"migrated": 0, "model": model, "was_stale": 0}

    bus.publish(
        "embedding.backfill.progress",
        {"done": 0, "total": stale_before, "model": model, "started": True},
    )

    def on_progress(done: int) -> None:
        bus.publish(
            "embedding.backfill.progress",
            {"done": done, "total": stale_before, "model": model},
        )

    migrated = backfill_embeddings(db, cfg, provider=model, on_progress=on_progress)
    bus.publish(
        "embedding.backfill.progress",
        {"done": migrated, "total": stale_before, "model": model, "finished": True},
    )
    log.info("embedding backfill: migrated %d/%d notes to %s", migrated, stale_before, model)
    return {"migrated": migrated, "model": model, "was_stale": stale_before}


@router.post("/embeddings/backfill")
async def start_embeddings_backfill(request: Request) -> dict:
    """Kick off the embedding migration in the background."""
    import asyncio

    st = request.app.state.st
    existing = getattr(st, "backfill_task", None)
    if existing is not None and not existing.done():
        return {"started": False, "reason": "already running"}

    async def _run() -> None:
        try:
            await asyncio.to_thread(backfill_embeddings_stream, st.db, st.cfg, st.bus)
        except Exception:
            log.exception("embedding backfill failed")
        finally:
            st.backfill_task = None

    st.backfill_task = asyncio.create_task(_run())
    return {"started": True}


@router.post("/reprocess")
async def start_reprocess(body: ReprocessIn, request: Request) -> dict:
    """#95 re-embed, and optionally re-enrich, every note — with progress.

    The confirm is a field on the body rather than a default, so a caller
    cannot overwrite a corpus by posting nothing: the default scope is the
    half that cannot destroy anything.
    """
    import asyncio

    st = request.app.state.st
    reason = validate_reprocess(st.cfg, body.scope, body.confirm)
    if reason:
        raise HTTPException(422, reason)
    existing = getattr(st, "reprocess_task", None)
    if existing is not None and not existing.done():
        return {"ok": False, "reason": "already running"}

    async def _run() -> None:
        try:
            await reprocess_corpus(
                st.db, st.cfg, st.bus, scope=body.scope, confirm=body.confirm
            )
        except Exception:
            log.exception("reprocess failed")
        finally:
            st.reprocess_task = None

    st.reprocess_task = asyncio.create_task(_run())
    return {"ok": True, "scope": body.scope, "started": True}
