import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SettingsView, { forceVaultResyncAction } from "../SettingsView";
import type { Settings, VaultSyncResult } from "../../types";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    settings: vi.fn(),
    resyncVault: vi.fn(),
    knownApps: vi.fn(),
    health: vi.fn(),
    updateSettings: vi.fn(),
    testLLM: vi.fn(),
    testWhisper: vi.fn(),
    setAppTracked: vi.fn(),
  },
}));

const mockBaseSettings: Settings = {
  host: "127.0.0.1",
  port: 7425,
  vault_dir: "/home/user/ObsidianVault",
  vault_sync: true,
  vault_writable: true,
  llm_provider: "openai",
  llm_base_url: "https://api.openai.com/v1",
  llm_model: "gpt-4o-mini",
  llm_timeout_secs: 30,
  transcribe_model: "base",
  transcribe_language: "en",
  transcribe_loaded: true,
  transcribe_cached_models: ["base"],
  yt_transcribe_fallback: false,
  yt_max_duration_min: 30,
  desktop_notifications: true,
  activity_enabled: true,
  activity_paused: false,
  activity_poll_secs: 5,
  activity_idle_after_min: 5,
  activity_excluded_apps: "",
  activity_auto_daily_log: true,
  activity_auto_weekly_log: true,
  activity_watch_dirs: "",
  activity_mirror_daily_log: true,
  activity_retention_days: 30,
  activity_running: true,
  config_path: "/home/user/.config/fleeting/config.toml",
};

describe("SettingsView Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.settings).mockResolvedValue(mockBaseSettings);
    vi.mocked(api.knownApps).mockResolvedValue([]);
    vi.mocked(api.health).mockResolvedValue({
      ok: true,
      version: "0.2.0",
      uptime_secs: 100,
      db: true,
      whisper_loaded: true,
      queue: 0,
    });
  });

  describe("Watcher Status Indicator Pill", () => {
    it("vault status pill shows Watching Vault when enabled and Sync Disabled when disabled", () => {
      // 1. When enabled:
      const enabledHtml = renderToStaticMarkup(
        <SettingsView
          onToast={vi.fn()}
          defaultTab="vault"
          initialSettings={mockBaseSettings}
        />
      );
      expect(enabledHtml).toContain("Watching Vault");
      expect(enabledHtml).toContain("🟢 Watching Vault (/home/user/ObsidianVault)");
      expect(enabledHtml).not.toContain("⚪ Sync Disabled");

      // 2. When disabled:
      const disabledHtml = renderToStaticMarkup(
        <SettingsView
          onToast={vi.fn()}
          defaultTab="vault"
          initialSettings={{ ...mockBaseSettings, vault_sync: false }}
        />
      );
      expect(disabledHtml).toContain("Sync Disabled");
      expect(disabledHtml).toContain("⚪ Sync Disabled");
      expect(disabledHtml).not.toContain("🟢 Watching Vault");
    });

    it("falls back to 'configured directory' if vault_dir is blank when enabled", () => {
      const html = renderToStaticMarkup(
        <SettingsView
          onToast={vi.fn()}
          defaultTab="vault"
          initialSettings={{ ...mockBaseSettings, vault_dir: "" }}
        />
      );
      expect(html).toContain("🟢 Watching Vault (configured directory)");
    });
  });

  describe("Force Vault Re-sync Action & Button", () => {
    it("renders Force Vault Re-sync button in vault settings", () => {
      const html = renderToStaticMarkup(
        <SettingsView
          onToast={vi.fn()}
          defaultTab="vault"
          initialSettings={mockBaseSettings}
        />
      );
      expect(html).toContain("Force Vault Re-sync");
    });

    it("renders summary message when resyncResult is present", () => {
      const summaryMsg = "Re-synced 12 notes, imported 4 notes, updated 7 tasks.";
      const html = renderToStaticMarkup(
        <SettingsView
          onToast={vi.fn()}
          defaultTab="vault"
          initialSettings={mockBaseSettings}
          initialResyncResult={summaryMsg}
        />
      );
      expect(html).toContain(summaryMsg);
      expect(html).toContain("data-testid=\"vault-resync-summary\"");
    });

    it("clicking Force Vault Re-sync calls api.resyncVault and displays the summary message", async () => {
      const resyncResult: VaultSyncResult = {
        ok: true,
        synced_notes: 8,
        imported_notes: 3,
        tasks_updated: 5,
      };
      vi.mocked(api.resyncVault).mockResolvedValue(resyncResult);

      const resyncStates: boolean[] = [];
      const setResyncing = vi.fn((val: boolean) => {
        resyncStates.push(val);
      });
      let displayedMessage: string | null = null;
      const setResyncResult = vi.fn((msg: string | null) => {
        displayedMessage = msg;
      });
      const onToast = vi.fn();

      const result = await forceVaultResyncAction(setResyncing, setResyncResult, onToast);

      // Verify api.resyncVault was called
      expect(api.resyncVault).toHaveBeenCalledTimes(1);

      // Verify returned result
      expect(result).toEqual(resyncResult);

      // Verify loading state changes: started as true, finished as false
      expect(resyncStates).toEqual([true, false]);

      // Verify summary message displayed
      const expectedSummary = "Re-synced 8 notes, imported 3 notes, updated 5 tasks.";
      expect(setResyncResult).toHaveBeenCalledWith(expectedSummary);
      expect(displayedMessage).toBe(expectedSummary);

      // Verify toast notification
      expect(onToast).toHaveBeenCalledWith(expectedSummary, "ok");
    });

    it("handles re-sync failure gracefully and shows error toast", async () => {
      vi.mocked(api.resyncVault).mockRejectedValue(new Error("Vault disk error"));

      const resyncStates: boolean[] = [];
      const setResyncing = vi.fn((val: boolean) => {
        resyncStates.push(val);
      });
      const setResyncResult = vi.fn();
      const onToast = vi.fn();

      const result = await forceVaultResyncAction(setResyncing, setResyncResult, onToast);

      expect(api.resyncVault).toHaveBeenCalledTimes(1);
      expect(result).toBeNull();
      expect(setResyncResult).not.toHaveBeenCalled();
      expect(onToast).toHaveBeenCalledWith("Vault disk error", "err");
      expect(resyncStates).toEqual([true, false]);
    });
  });
});

describe("LLM API key field", () => {
  it("is hidden for ollama", () => {
    const html = renderToStaticMarkup(
      <SettingsView
        onToast={vi.fn()}
        defaultTab="ai"
        initialSettings={{ ...mockBaseSettings, llm_provider: "ollama" }}
      />,
    );
    expect(html).not.toContain("API Key");
  });

  it("is shown for the custom provider", () => {
    const html = renderToStaticMarkup(
      <SettingsView
        onToast={vi.fn()}
        defaultTab="ai"
        initialSettings={{ ...mockBaseSettings, llm_provider: "custom" }}
      />,
    );
    expect(html).toContain("API Key");
    expect(html).toContain('type="password"');
  });

  it("reports a stored key without revealing it", () => {
    const html = renderToStaticMarkup(
      <SettingsView
        onToast={vi.fn()}
        defaultTab="ai"
        initialSettings={{
          ...mockBaseSettings,
          llm_provider: "custom",
          llm_api_key_set: true,
        }}
      />,
    );
    expect(html).toContain("A key is stored");
    expect(html).toContain("clear");
    // the field must never be prefilled with the secret
    expect(html).not.toContain("sk-");
  });
});
