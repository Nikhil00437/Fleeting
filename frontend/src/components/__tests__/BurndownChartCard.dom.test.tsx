/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import BurndownChartCard from "../BurndownChartCard";
import type { BurndownData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockBurndownData: BurndownData = {
  window_days: 30,
  current_backlog: 12,
  current_open_tasks: 8,
  current_pending_captures: 4,
  total_added: 25,
  total_resolved: 30,
  avg_daily_resolved: 1.0,
  days_to_zero: 12.0,
  projected_date: "2026-10-20",
  series: [
    {
      day: "2026-10-01",
      tasks_added: 2,
      tasks_completed: 1,
      captures_added: 1,
      captures_resolved: 1,
      added: 3,
      resolved: 2,
      net: 1,
      open_backlog: 17,
      ideal_burndown: 20.0,
    },
    {
      day: "2026-10-02",
      tasks_added: 1,
      tasks_completed: 3,
      captures_added: 0,
      captures_resolved: 1,
      added: 1,
      resolved: 4,
      net: -3,
      open_backlog: 14,
      ideal_burndown: 10.0,
    },
    {
      day: "2026-10-03",
      tasks_added: 1,
      tasks_completed: 2,
      captures_added: 1,
      captures_resolved: 2,
      added: 2,
      resolved: 4,
      net: -2,
      open_backlog: 12,
      ideal_burndown: 0.0,
    },
  ],
};

describe("BurndownChartCard (#423)", () => {
  it("renders backlog KPIs, trajectory, and legend", async () => {
    vi.spyOn(api, "burndown").mockResolvedValue(mockBurndownData);

    render(<BurndownChartCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Backlog Burndown")).toBeDefined();
    });

    expect(screen.getByText("12")).toBeDefined(); // Current Backlog
    expect(screen.getByText(/\(8 tasks \+ 4 inbox\)/)).toBeDefined();
    expect(screen.getByText("1")).toBeDefined(); // Resolution velocity
    expect(screen.getByText(/~12d/)).toBeDefined(); // Days to zero
    expect(screen.getByText("Actual Backlog")).toBeDefined();
    expect(screen.getByText("Ideal Burndown")).toBeDefined();
  });

  it("handles switching window days", async () => {
    const spy = vi.spyOn(api, "burndown").mockResolvedValue(mockBurndownData);

    render(<BurndownChartCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Backlog Burndown")).toBeDefined();
    });

    const btn14d = screen.getByRole("button", { name: "14d" });
    fireEvent.click(btn14d);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(14);
    });
  });

  it("renders zero backlog state correctly", async () => {
    vi.spyOn(api, "burndown").mockResolvedValue({
      ...mockBurndownData,
      current_backlog: 0,
      current_open_tasks: 0,
      current_pending_captures: 0,
      days_to_zero: 0.0,
    });

    render(<BurndownChartCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Zero Backlog Achieved!")).toBeDefined();
    });
  });
});
