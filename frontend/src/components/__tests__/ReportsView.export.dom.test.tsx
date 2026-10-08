// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import ReportsView from "../ReportsView";
import { api } from "../../api";
import type { DailyLog } from "../../types";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockLog: DailyLog = {
  day: "2026-10-08",
  summary_md: "# Daily Digest — 2026-10-08\n\nDaily report content.",
  edited_body: null,
  edited: 0,
  model: "ollama",
  created_at: "2026-10-08T12:00:00Z",
};

describe("ReportsView export (#74)", () => {
  it("renders export buttons for Markdown and PDF with correct URLs", async () => {
    vi.spyOn(api, "dailyLog").mockResolvedValue({ ...mockLog });
    vi.spyOn(api, "dailyReflection").mockResolvedValue({
      day: "2026-10-08",
      prompts: [],
      note: null,
    });
    vi.spyOn(api, "weeklyLog").mockResolvedValue({
      week: "2026-10-05",
      this_week: "2026-10-05",
      report: null,
      summary: { total_seconds: 0, days: [] } as any,
    });
    vi.spyOn(api, "orphans").mockResolvedValue({
      single_use_tags: [],
      untagged_notes: [],
      unlinked_tasks: [],
    });

    render(<ReportsView onToast={() => {}} refreshKey={0} />);

    await waitFor(() => {
      const mdBtn = screen.getByLabelText("Export Markdown");
      expect(mdBtn).toBeDefined();
      expect(mdBtn.getAttribute("href")).toContain("/api/activity/daily-log/2026-10-08/export?format=md");

      const pdfBtn = screen.getByLabelText("Export PDF");
      expect(pdfBtn).toBeDefined();
      expect(pdfBtn.getAttribute("href")).toContain("/api/activity/daily-log/2026-10-08/export?format=pdf");
    });
  });
});
