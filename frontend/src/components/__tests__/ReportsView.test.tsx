import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ReportsView from "../ReportsView";
import SystemTab from "../settings/SystemTab";
import type { Settings } from "../../types";

vi.mock("../../api", () => ({
  api: {
    dailyLog: vi.fn(),
    generateDailyLog: vi.fn(),
    weeklyLog: vi.fn(),
    generateWeeklyLog: vi.fn(),
  },
}));

const settings = {
  host: "127.0.0.1", port: 7425, vault_dir: "/v", vault_sync: true, vault_writable: true,
  llm_provider: "ollama", llm_base_url: "http://x", llm_model: "m", llm_timeout_secs: 120,
  transcribe_model: "base", transcribe_language: "auto", transcribe_loaded: true,
  transcribe_cached_models: [], yt_transcribe_fallback: true, yt_max_duration_min: 45,
  desktop_notifications: true, activity_enabled: true, activity_paused: false,
  activity_poll_secs: 20, activity_idle_after_min: 3, activity_excluded_apps: "",
  activity_auto_daily_log: true, activity_watch_dirs: "", activity_mirror_daily_log: false,
  activity_auto_weekly_log: true, activity_retention_days: 30, activity_running: false,
  config_path: "/c",
} as unknown as Settings;

function render() {
  return renderToStaticMarkup(<ReportsView onToast={() => {}} refreshKey={0} />);
}

describe("ReportsView", () => {
  it("renders both reports on one page", () => {
    const html = render();
    expect(html).toContain("Reports");
    expect(html).toContain("Daily AI Executive Digest");
    expect(html).toContain("Weekly Digest");
  });

  it("offers day navigation for the daily report", () => {
    const html = render();
    expect(html).toContain("Previous day");
    expect(html).toContain("Next day");
  });

  it("explains what the page is for", () => {
    expect(render()).toMatch(/daily and weekly summaries/i);
  });

  it("offers a generate action for both", () => {
    const html = render();
    // weekly card + daily card each get one
    expect(html.match(/Generate|Regen/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("has no day-scoped dashboard chrome left", () => {
    // The Timeline kept the charts; Reports is only the summaries. If these
    // ever come back it means the split has been undone.
    const html = render();
    expect(html).not.toContain("Hourly Intensity");
    expect(html).not.toContain("Session Ribbon");
  });
});

describe("shortcut legend matches the real key bindings", () => {
  it("documents r for Reports, and a for the assistant", () => {
    // The legend used to say `a` opened the Timeline while App.tsx bound it to
    // the assistant — a stale hand-maintained list. These pin the two entries
    // most likely to drift again.
    const html = renderToStaticMarkup(<SystemTab health={null} s={settings} onToast={() => {}} loadAll={() => {}} embedding={null} onBackfill={() => {}} backfillBusy={false} />);
    expect(html).toMatch(/>\s*r\s*<\/kbd>/);
    expect(html).toMatch(/>\s*r\s*<\/kbd>\s*\{?\}?\s*Reports/);
    expect(html).toMatch(/>\s*a\s*<\/kbd[\s\S]{0,80}Ask Fleeting/);
    expect(html).not.toMatch(/>\s*a\s*<\/kbd[\s\S]{0,80}Timeline Pane/);
  });
});
