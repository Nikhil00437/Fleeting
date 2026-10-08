/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import EstimateAccuracyCard from "../EstimateAccuracyCard";
import type { EstimateAccuracyData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockData: EstimateAccuracyData = {
  total_evaluated: 3,
  untracked_count: 2,
  total_estimated_min: 150,
  total_spent_min: 180,
  avg_error_min: 20.0,
  overall_accuracy_pct: 83.3,
  average_ratio: 1.2,
  bias: "underestimating",
  counts: {
    on_target: 1,
    underestimated: 2,
    overestimated: 0,
  },
  by_priority: {
    P1: { count: 2, estimated_min: 120, spent_min: 130, accuracy_pct: 92.3 },
    P2: { count: 1, estimated_min: 30, spent_min: 50, accuracy_pct: 60.0 },
  },
  items: [
    {
      id: "t1",
      text: "Task A",
      done: 1,
      priority: "P1",
      due_date: null,
      estimate_min: 60,
      spent_min: 60,
      diff_min: 0,
      ratio: 1.0,
      accuracy_pct: 100.0,
      status: "on_target",
      repo: "fleeting",
      created_at: "2026-10-08T09:00:00Z",
      completed_at: "2026-10-08T10:00:00Z",
    },
    {
      id: "t2",
      text: "Task B",
      done: 1,
      priority: "P1",
      due_date: null,
      estimate_min: 60,
      spent_min: 70,
      diff_min: 10,
      ratio: 1.17,
      accuracy_pct: 85.7,
      status: "underestimated",
      repo: "fleeting",
      created_at: "2026-10-08T09:00:00Z",
      completed_at: "2026-10-08T10:10:00Z",
    },
  ],
};

describe("EstimateAccuracyCard (#170)", () => {
  it("renders empty state when no evaluated tasks", async () => {
    vi.spyOn(api, "estimateAccuracy").mockResolvedValue({
      total_evaluated: 0,
      untracked_count: 1,
      total_estimated_min: 0,
      total_spent_min: 0,
      avg_error_min: 0.0,
      overall_accuracy_pct: 0.0,
      average_ratio: 1.0,
      bias: "no_data",
      counts: { on_target: 0, underestimated: 0, overestimated: 0 },
      by_priority: {},
      items: [],
    });

    render(<EstimateAccuracyCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Time-Estimate Accuracy")).toBeDefined();
      expect(screen.getByText(/No completed tasks with both estimated and actual/)).toBeDefined();
      expect(screen.getByText(/1 task has estimates waiting/)).toBeDefined();
    });
  });

  it("renders metrics, bias, priority breakdown and allows toggling task list", async () => {
    vi.spyOn(api, "estimateAccuracy").mockResolvedValue(mockData);

    render(<EstimateAccuracyCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Time-Estimate Accuracy")).toBeDefined();
      expect(screen.getByText("83.3%")).toBeDefined();
      expect(screen.getByText("Underestimating (tasks take longer)")).toBeDefined();
      expect(screen.getByText("±20m")).toBeDefined();
      expect(screen.getByText("150m")).toBeDefined();
      expect(screen.getByText("180m")).toBeDefined();
    });

    // Toggle tasks
    const toggleBtn = screen.getByText(/Show evaluated tasks/);
    fireEvent.click(toggleBtn);

    await waitFor(() => {
      expect(screen.getByText("Task A")).toBeDefined();
      expect(screen.getByText("Task B")).toBeDefined();
    });
  });
});
