/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import TaskFunnelCard from "../TaskFunnelCard";
import type { TaskFunnelData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockFunnelData: TaskFunnelData = {
  window_days: 30,
  total_tasks: 20,
  stages: [
    {
      stage: "captured",
      name: "Captured",
      count: 20,
      pct_of_captured: 100.0,
      dropoff_pct: 0.0,
    },
    {
      stage: "planned",
      name: "Planned",
      count: 15,
      pct_of_captured: 75.0,
      dropoff_pct: 25.0,
    },
    {
      stage: "started",
      name: "Started",
      count: 10,
      pct_of_captured: 50.0,
      dropoff_pct: 33.3,
    },
    {
      stage: "completed",
      name: "Completed",
      count: 6,
      pct_of_captured: 30.0,
      dropoff_pct: 40.0,
    },
  ],
  by_priority: {
    P1: { captured: 8, planned: 8, started: 6, completed: 5 },
    P2: { captured: 10, planned: 6, started: 4, completed: 1 },
    P3: { captured: 2, planned: 1, started: 0, completed: 0 },
  },
};

describe("TaskFunnelCard (#250)", () => {
  it("renders stages, drop-off, and priority conversion breakdown", async () => {
    vi.spyOn(api, "taskFunnel").mockResolvedValue(mockFunnelData);

    render(<TaskFunnelCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Task Conversion Funnel")).toBeDefined();
    });

    expect(screen.getByText("30%")).toBeDefined(); // Overall completion rate
    expect(screen.getByText("Captured")).toBeDefined();
    expect(screen.getByText("Planned")).toBeDefined();
    expect(screen.getByText("Started")).toBeDefined();
    expect(screen.getByText("Completed")).toBeDefined();

    // Priority breakdown
    expect(screen.getByText("Conversion by Priority")).toBeDefined();
    expect(screen.getByText("P1")).toBeDefined();
    expect(screen.getByText("63%")).toBeDefined(); // 5/8 = 62.5% -> 63%
  });

  it("changes window days filter when clicked", async () => {
    const spy = vi.spyOn(api, "taskFunnel").mockResolvedValue(mockFunnelData);

    render(<TaskFunnelCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Task Conversion Funnel")).toBeDefined();
    });

    const btn7d = screen.getByRole("button", { name: "7d" });
    fireEvent.click(btn7d);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(7);
    });
  });

  it("handles empty task funnel gracefully", async () => {
    vi.spyOn(api, "taskFunnel").mockResolvedValue({
      window_days: 30,
      total_tasks: 0,
      stages: [],
      by_priority: {},
    });

    render(<TaskFunnelCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText(/No tasks recorded for this time window/)).toBeDefined();
    });
  });
});
