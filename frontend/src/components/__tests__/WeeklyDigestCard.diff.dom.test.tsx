/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import WeeklyDigestCard from "../WeeklyDigestCard";
import { api } from "../../api";
import type { WeeklyLogOut } from "../../types";

vi.mock("../../api", () => ({
  api: {
    weeklyLog: vi.fn(),
    generateWeeklyLog: vi.fn(),
  },
}));

describe("WeeklyDigestCard diff narrative (#346)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-12T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders the plain-English weekly diff callout when present", async () => {
    const mockData: WeeklyLogOut = {
      week: "2026-10-05",
      this_week: "2026-10-12",
      report: {
        week_start: "2026-10-05",
        summary_md: "# Weekly Digest — 2026-10-05\n\nWeekly summary content",
        model: "ollama",
        created_at: "2026-10-12T00:00:00Z",
      },
      summary: {
        week_start: "2026-10-05",
        week_end: "2026-10-11",
        days: [
          { day: "2026-10-05", seconds: 7200, busy: true },
          { day: "2026-10-06", seconds: 7200, busy: true },
          { day: "2026-10-07", seconds: 0, busy: false },
          { day: "2026-10-08", seconds: 0, busy: false },
          { day: "2026-10-09", seconds: 0, busy: false },
          { day: "2026-10-10", seconds: 0, busy: false },
          { day: "2026-10-11", seconds: 0, busy: false },
        ],
        apps: [{ app_class: "code", seconds: 14400 }],
        total_seconds: 14400,
        busiest_day: "2026-10-05",
        quietest_day: "2026-10-07",
        daily_logs: [],
        total_tasks: 2,
        open_tasks: 1,
        commits: [],
        files_touched: 0,
        diff: {
          current_week: "2026-10-05",
          previous_week: "2026-09-28",
          current_seconds: 14400,
          previous_seconds: 7200,
          delta_seconds: 7200,
          delta_pct: 100.0,
          current_active_days: 2,
          previous_active_days: 1,
          app_shifts: [
            {
              app_class: "code",
              delta_seconds: 7200,
              current_seconds: 14400,
              previous_seconds: 7200,
            },
          ],
          narrative: "Focus was up +100% (+2h) compared to last week (4h vs 2h across 2 active days). Most notably, time in code increased by 2h.",
        },
      },
      diff: {
        current_week: "2026-10-05",
        previous_week: "2026-09-28",
        current_seconds: 14400,
        previous_seconds: 7200,
        delta_seconds: 7200,
        delta_pct: 100.0,
        current_active_days: 2,
        previous_active_days: 1,
        app_shifts: [
          {
            app_class: "code",
            delta_seconds: 7200,
            current_seconds: 14400,
            previous_seconds: 7200,
          },
        ],
        narrative: "Focus was up +100% (+2h) compared to last week (4h vs 2h across 2 active days). Most notably, time in code increased by 2h.",
      },
    };

    vi.mocked(api.weeklyLog).mockResolvedValue(mockData);

    render(<WeeklyDigestCard onToast={() => {}} refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByTestId("weekly-diff-callout")).toBeDefined();
    });

    const callout = screen.getByTestId("weekly-diff-callout");
    expect(callout.textContent).toContain("vs. last week:");
    expect(callout.textContent).toContain("Focus was up +100% (+2h) compared to last week");
    expect(callout.textContent).toContain("time in code increased by 2h");
  });
});
