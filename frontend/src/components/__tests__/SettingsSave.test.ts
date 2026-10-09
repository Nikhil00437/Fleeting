import { describe, expect, it } from "vitest";
import {
  applySettingsChange,
  errorMessage,
  reconcileSettings,
} from "../settingsState";
import type { Settings } from "../../types";

const base: Settings = {
  host: "127.0.0.1",
  port: 7425,
  vault_dir: "/home/user/Vault",
  vault_sync: true,
  vault_writable: true,
  llm_provider: "ollama",
  llm_base_url: "http://127.0.0.1:11434",
  llm_model: "",
  llm_fallback_models: "",
  llm_preferred_tags: "",
  llm_enrich_model: "",
  llm_report_model: "",
  llm_assistant_model: "",
  entities_stale_days: 0,
  writing_style_guide: "",
  llm_timeout_secs: 120,
  transcribe_model: "base",
  transcribe_language: "auto",
  transcribe_vocabulary: "",
  transcribe_translate: false,
  transcribe_cleanup_audio: false,
  transcribe_keep_audio: true,
  transcribe_voice_punctuation: false,
  transcribe_auto_format: false,
  transcribe_replacements: "",
  transcribe_diarize: false,
  transcribe_hf_token_set: false,
  transcribe_loaded: false,
  transcribe_cached_models: [],
  yt_transcribe_fallback: true,
  yt_max_duration_min: 45,
  desktop_notifications: true,
  activity_enabled: true,
  activity_paused: false,
  activity_poll_secs: 20,
  activity_idle_after_min: 3,
  activity_idle_source: "auto",
  activity_idle_available: true,
  activity_excluded_apps: "zen",
  activity_auto_daily_log: true,
  activity_auto_weekly_log: true,
  activity_watch_dirs: "",
  activity_mirror_daily_log: false,
  activity_retention_days: 30,
  activity_running: false,
  config_path: "/home/user/.config/fleeting/config.toml",
};

describe("optimistic settings save", () => {
  it("shows the new value immediately", () => {
    const next = applySettingsChange(base, { llm_timeout_secs: 45 });
    expect(next.llm_timeout_secs).toBe(45);
    expect(next.port).toBe(7425);
  });

  it("restores the previous value when the save is rejected", () => {
    const previous = { ...base };
    let state = applySettingsChange(previous, { llm_timeout_secs: 6 });
    state = reconcileSettings(state, previous, null);
    expect(state.llm_timeout_secs).toBe(120);
  });

  it("adopts the server response as the source of truth", () => {
    let state = applySettingsChange(base, { llm_timeout_secs: 45 });
    const server: Settings = { ...base, llm_timeout_secs: 30, llm_model: "qwen3:8b" };
    state = reconcileSettings(state, base, server);
    expect(state.llm_timeout_secs).toBe(30);
    expect(state.llm_model).toBe("qwen3:8b");
  });

  it("ignores a null server response without wiping state", () => {
    const previous = { ...base };
    const state = reconcileSettings(
      applySettingsChange(previous, { port: 9000 }),
      previous,
      null,
    );
    expect(state).toEqual(previous);
  });

  it("does not mutate the input", () => {
    const original = { ...base };
    applySettingsChange(original, { port: 1 });
    expect(original.port).toBe(7425);
  });
});

describe("errorMessage", () => {
  it("prefers the server message", () => {
    expect(errorMessage(new Error("Validation failed"))).toBe("Validation failed");
  });

  it("falls back to stringifying non-Errors", () => {
    expect(errorMessage("boom")).toBe("boom");
  });

  it("never returns an empty message", () => {
    expect(errorMessage(new Error(""))).not.toBe("");
    expect(errorMessage(undefined)).not.toBe("");
    expect(errorMessage(null)).not.toBe("");
  });
});