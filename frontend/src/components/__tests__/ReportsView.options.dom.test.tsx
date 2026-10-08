// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  summary_md: "# Daily Digest — 2026-10-08\n\nExisting report content.",
  edited_body: null,
  edited: 0,
  model: "ollama",
  created_at: "2026-10-08T12:00:00Z",
};

describe("ReportsView options (#68, #67, #343, #344, #345, #348)", () => {
  it("toggles options panel and passes configured options to generateDailyLog", async () => {
    const onToast = vi.fn();
    vi.spyOn(api, "dailyLog").mockResolvedValue({ ...mockLog });
    const genSpy = vi.spyOn(api, "generateDailyLog").mockResolvedValue({
      ...mockLog,
      summary_md: "Regenerated standup report.",
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

    render(<ReportsView onToast={onToast} refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText(/Existing report content/i)).toBeDefined();
    });

    // Options drawer should not be visible initially
    expect(screen.queryByLabelText("Custom instructions")).toBeNull();

    // Click options button
    const optionsBtn = screen.getByLabelText("Report options");
    fireEvent.click(optionsBtn);

    // Options controls should now be visible
    expect(screen.getByLabelText("Custom instructions")).toBeDefined();

    // Select 'standup' tone
    const standupBtn = screen.getByText("standup");
    fireEvent.click(standupBtn);

    // Select 'short' length
    const shortBtn = screen.getByText("short");
    fireEvent.click(shortBtn);

    // Enter custom instructions
    const customInput = screen.getByLabelText("Custom instructions");
    fireEvent.change(customInput, { target: { value: "Focus on backend architecture" } });

    // Toggle highlights only
    const highlightsCb = screen.getByLabelText("Highlights only");
    fireEvent.click(highlightsCb);

    // Click Regen
    const regenBtn = screen.getByText("Regen");
    fireEvent.click(regenBtn);

    await waitFor(() => {
      expect(genSpy).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Boolean),
        expect.objectContaining({
          tone: "standup",
          length: "short",
          highlights_only: true,
          prompt_override: "Focus on backend architecture",
        })
      );
    });
  });
});
