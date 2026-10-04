"""Settings read/write + connection tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from ..config import CONFIG_PATH, LLMConfig, expand_path, save_config
from ..models import LLMProbeIn, SettingsIn
from ..services import llm

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
        "transcribe_model": cfg.transcribe.model,
        "transcribe_language": cfg.transcribe.language,
        "transcribe_loaded": st.transcriber.is_ready(),
        "transcribe_cached_models": st.transcriber.cached_models(),
        "transcribe_progress": st.transcriber.progress,
        "yt_transcribe_fallback": cfg.youtube.transcribe_fallback,
        "yt_max_duration_min": cfg.youtube.max_duration_min,
        "desktop_notifications": cfg.notifications.desktop,
        "activity_enabled": cfg.activity.enabled,
        "activity_paused": st.activity.is_paused() if st.activity else False,
        "activity_poll_secs": cfg.activity.poll_secs,
        "activity_idle_after_min": cfg.activity.idle_after_min,
        "activity_excluded_apps": cfg.activity.excluded_apps,
        "activity_auto_daily_log": cfg.activity.auto_daily_log,
        "activity_watch_dirs": cfg.activity.watch_dirs,
        "activity_mirror_daily_log": cfg.activity.mirror_daily_log,
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
    if body.transcribe_model is not None:
        if body.transcribe_model != cfg.transcribe.model:
            cfg.transcribe.model = body.transcribe_model
            st.transcriber.set_model(body.transcribe_model)
    if body.transcribe_language is not None:
        cfg.transcribe.language = body.transcribe_language.strip().lower() or "auto"
    if body.yt_transcribe_fallback is not None:
        cfg.youtube.transcribe_fallback = body.yt_transcribe_fallback
    if body.yt_max_duration_min is not None:
        cfg.youtube.max_duration_min = body.yt_max_duration_min
    if body.desktop_notifications is not None:
        cfg.notifications.desktop = body.desktop_notifications
    if body.activity_enabled is not None:
        cfg.activity.enabled = body.activity_enabled
    if body.activity_poll_secs is not None:
        cfg.activity.poll_secs = max(5, body.activity_poll_secs)
    if body.activity_idle_after_min is not None:
        cfg.activity.idle_after_min = max(1, body.activity_idle_after_min)
    if body.activity_excluded_apps is not None:
        cfg.activity.excluded_apps = body.activity_excluded_apps.strip()
    if body.activity_auto_daily_log is not None:
        cfg.activity.auto_daily_log = body.activity_auto_daily_log
    if body.activity_watch_dirs is not None:
        cfg.activity.watch_dirs = body.activity_watch_dirs.strip()
    if body.activity_mirror_daily_log is not None:
        cfg.activity.mirror_daily_log = body.activity_mirror_daily_log

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
    return await llm.check_llm(probe)


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


