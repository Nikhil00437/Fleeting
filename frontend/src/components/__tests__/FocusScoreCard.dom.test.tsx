/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import FocusScoreCard from "../FocusScoreCard";
import type { FocusScoreTrend } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockTrend: FocusScoreTrend = {
  days: [
    {
      day: "2026-10-06",
      score: 65,
      grade: "Productive",
      total_seconds: 7200,
      components: { duration: 20.0, stretch: 25.0, project: 20.0 },
      switches: 6,
      seconds_per_switch: 1200,
      project_seconds: 5000,
    },
    {
      day: "2026-10-07",
      score: 75,
      grade: "Productive",
      total_seconds: 10800,
      components: { duration: 30.0, stretch: 25.0, project: 20.0 },
      switches: 8,
      seconds_per_switch: 1350,
      project_seconds: 8000,
    },
    {
      day: "2026-10-08",
      score: 88,
      grade: "Deep Focus",
      total_seconds: 14400,
      components: { duration: 40.0, stretch: 28.0, project: 20.0 },
      switches: 10,
      seconds_per_switch: 1440,
      project_seconds: 11000,
    },
  ],
  average_score: 76.0,
  streak_days: 3,
  direction: "improving",
  active_days_count: 3,
  best_day: { day: "2026-10-08", score: 88 },
};

describe("FocusScoreCard (#57)", () => {
  it("renders focus score KPIs, trend chart, and components", async () => {
    vi.spyOn(api, "focusScoreTrend").mockResolvedValue(mockTrend);

    render(<FocusScoreCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Daily Focus Score Trend")).toBeDefined();
      expect(screen.getAllByText(/88\/100/).length).toBeGreaterThan(0);
      expect(screen.getByText("Deep Focus")).toBeDefined();
      expect(screen.getByText("76")).toBeDefined();
      expect(screen.getByText(/3 days/)).toBeDefined();
      expect(screen.getByText("↑ Improving")).toBeDefined();
      expect(screen.getByText(/40\/40 pts/)).toBeDefined();
    });
  });

  it("selects day when clicked on a bar", async () => {
    vi.spyOn(api, "focusScoreTrend").mockResolvedValue(mockTrend);

    const onSelectDay = vi.fn();
    render(<FocusScoreCard refreshKey={0} onSelectDay={onSelectDay} />);

    await waitFor(() => {
      expect(screen.getByTitle(/2026-10-08: 88\/100/)).toBeDefined();
    });

    fireEvent.click(screen.getByTitle(/2026-10-08: 88\/100/));
    expect(onSelectDay).toHaveBeenCalledWith("2026-10-08");
  });

  it("switches window range", async () => {
    const spy = vi.spyOn(api, "focusScoreTrend").mockResolvedValue(mockTrend);

    render(<FocusScoreCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("7d")).toBeDefined();
    });

    fireEvent.click(screen.getByText("7d"));
    expect(spy).toHaveBeenCalledWith(7);
  });
});
