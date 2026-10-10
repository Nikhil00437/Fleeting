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
  llm_preferred_tags: "",
  llm_embedding_model: "",
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

describe("AiTab preferred tags (#257)", () => {
  afterEach(() => {
    cleanup();
  });

  it("labels the vocabulary field", () => {
    renderTab();
    const input = screen.getByLabelText(/preferred tags/i) as HTMLInputElement;
    expect(input.id).toBe("llm-preferred-tags");
  });

  it("shows the configured vocabulary", () => {
    renderTab({ llm_preferred_tags: "homelab, reading" });
    const input = screen.getByLabelText(/preferred tags/i) as HTMLInputElement;
    expect(input.value).toBe("homelab, reading");
  });

  it("says the vocabulary is enforced, not just suggested", () => {
    const { container } = renderTab();
    expect(container.textContent).toMatch(/snapped onto/i);
  });

  it("is hidden with no provider configured", () => {
    renderTab({ llm_provider: "none" });
    expect(screen.queryByLabelText(/preferred tags/i)).toBeNull();
  });
});

describe("AiTab style guide (#451)", () => {
  afterEach(() => {
    cleanup();
  });

  it("labels the style guide field", () => {
    renderTab();
    const field = screen.getByLabelText(/style guide/i) as HTMLTextAreaElement;
    expect(field.id).toBe("writing-style-guide");
  });

  it("shows the configured guide", () => {
    renderTab({ writing_style_guide: "No semicolons." });
    expect((screen.getByLabelText(/style guide/i) as HTMLTextAreaElement).value).toBe(
      "No semicolons.",
    );
  });

  it("says it applies everywhere rather than to one command", () => {
    const { container } = renderTab();
    expect(container.textContent).toMatch(/every rewrite and title/i);
  });

  it("is hidden with no provider configured", () => {
    renderTab({ llm_provider: "none" });
    expect(screen.queryByLabelText(/style guide/i)).toBeNull();
  });
});

describe("AiTab per-task models (#92)", () => {
  afterEach(() => {
    cleanup();
  });

  it("offers an override for each of the three jobs", () => {
    renderTab();
    expect(screen.getByLabelText("Capture")).toBeTruthy();
    expect(screen.getByLabelText("Reports")).toBeTruthy();
    expect(screen.getByLabelText("Assistant")).toBeTruthy();
  });

  it("shows the configured overrides", () => {
    renderTab({ llm_enrich_model: "qwen2.5:3b", llm_model: "qwen3:8b" });
    expect((screen.getByLabelText("Capture") as HTMLInputElement).value).toBe("qwen2.5:3b");
  });

  it("shows an empty override as the model above", () => {
    // Blank means "use the model above", so the placeholder says so.
    renderTab({ llm_model: "qwen3:8b" });
    const input = screen.getByLabelText("Reports") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(input.placeholder).toBe("qwen3:8b");
  });

  it("is hidden with no provider configured", () => {
    renderTab({ llm_provider: "none" });
    expect(screen.queryByLabelText("Reports")).toBeNull();
  });
});

describe("AiTab embedding model", () => {
  afterEach(() => {
    cleanup();
  });

  it("has its own field, separate from the chat model", () => {
    renderTab({ llm_model: "ornith-1.5:9b" });
    const input = screen.getByLabelText(/embedding model/i) as HTMLInputElement;
    expect(input.id).toBe("llm-embedding-model");
    expect(input.value).toBe("");
  });

  it("says blank falls back to the model above", () => {
    renderTab({ llm_model: "ornith-1.5:9b" });
    const input = screen.getByLabelText(/embedding model/i) as HTMLInputElement;
    expect(input.placeholder).toBe("ornith-1.5:9b");
  });

  it("warns that changing it re-embeds every note", () => {
    const { container } = renderTab();
    expect(container.textContent).toMatch(/re-embeds every note/i);
  });

  it("shows the configured embedding model", () => {
    renderTab({ llm_embedding_model: "embeddinggemma-2:270m" });
    expect((screen.getByLabelText(/embedding model/i) as HTMLInputElement).value).toBe(
      "embeddinggemma-2:270m",
    );
  });
});
