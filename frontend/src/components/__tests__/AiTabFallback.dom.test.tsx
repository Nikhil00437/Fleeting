/**
 * #266 fallback chain field in the AI settings tab.
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import AiTab from "../settings/AiTab";
import type { Settings } from "../../types";

const base: Settings = {
  host: "127.0.0.1",
  port: 7425,
  vault_dir: "/tmp/v",
  vault_sync: true,
  vault_writable: true,
  llm_provider: "ollama",
  llm_base_url: "http://127.0.0.1:11434",
  llm_model: "qwen3:8b",
  llm_fallback_models: "",
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
  transcribe_loaded: false,
  yt_transcribe_fallback: true,
  yt_max_duration_min: 120,
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
  activity_watch_dirs: "~/Projects",
  activity_mirror_daily_log: false,
  activity_retention_days: 30,
  activity_running: false,
  config_path: "/tmp/config.toml",
};

function renderTab(overrides: Partial<Settings> = {}) {
  return render(
    <AiTab
      s={{ ...base, ...overrides }}
      patch={() => {}}
      save={async () => {}}
      loadAll={() => {}}
      saving={false}
    />,
  );
}

describe("AiTab fallback models (#266)", () => {
  afterEach(() => {
    cleanup();
  });

  it("labels the field and links it for screen readers", () => {
    renderTab();
    const input = screen.getByLabelText(/fallback models/i) as HTMLInputElement;
    expect(input.id).toBe("llm-fallback-models");
  });

  it("shows the configured chain", () => {
    renderTab({ llm_fallback_models: "qwen2.5:3b, llama3.2:1b" });
    const input = screen.getByLabelText(/fallback models/i) as HTMLInputElement;
    expect(input.value).toBe("qwen2.5:3b, llama3.2:1b");
  });

  it("explains that the timeout is shared across the chain", () => {
    const { container } = renderTab();
    expect(container.textContent).toMatch(/equal share of the timeout/i);
  });

  it("hides the field when no provider is configured", () => {
    renderTab({ llm_provider: "none" });
    expect(screen.queryByLabelText(/fallback models/i)).toBeNull();
  });
});
