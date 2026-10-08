// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ActivityHeatmap from "../ActivityHeatmap";
import FocusMetrics from "../FocusMetrics";
import { api } from "../../api";
import type { HeatmapData } from "../../types";

const grid = (over: Partial<HeatmapData> = {}): HeatmapData => ({
  from: "2026-09-30", // a Wednesday
  to: "2026-10-08",
  weeks: 2,
  cells: [
    { day: "2026-09-30", minutes: 30 },
    { day: "2026-10-01", minutes: 300 },
    { day: "2026-10-08", minutes: 120 },
  ],
  peak_minutes: 300,
  ...over,
});

beforeAll(() => {
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

describe("ActivityHeatmap (#59)", () => {
  it("renders one cell per tracked day and opens it on click", async () => {
    vi.spyOn(api, "activityHeatmap").mockResolvedValue(grid());
    const onOpenDay = vi.fn();
    render(<ActivityHeatmap onOpenDay={onOpenDay} />);

    const cell = await screen.findByLabelText("2026-10-01: 300 minutes");
    expect(cell.className).toContain("bg-ember-300"); // the busiest cell
    expect(screen.getByLabelText("2026-09-30: 30 minutes").className).toContain("bg-ember-500/25");
    fireEvent.click(cell);
    expect(onOpenDay).toHaveBeenCalledWith("2026-10-01");
  });

  it("pads the first column so days line up with weekdays", async () => {
    vi.spyOn(api, "activityHeatmap").mockResolvedValue(grid());
    const { container } = render(<ActivityHeatmap />);
    await screen.findByLabelText("2026-10-01: 300 minutes");
    const firstColumn = container.querySelectorAll("[aria-label$='minutes']")[0];
    // Wednesday means two empty cells above it in the first column
    expect(firstColumn.parentElement?.children.length).toBeGreaterThanOrEqual(3);
  });

  it("renders nothing when the grid cannot be loaded", async () => {
    vi.spyOn(api, "activityHeatmap").mockRejectedValue(new Error("offline"));
    const { container } = render(<ActivityHeatmap />);
    await waitFor(() => expect(api.activityHeatmap).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });

  it("switches metric between activity, notes and tasks (#252)", async () => {
    const spy = vi.spyOn(api, "activityHeatmap").mockResolvedValue(grid());
    render(<ActivityHeatmap />);
    await screen.findByLabelText("2026-10-01: 300 minutes");

    const notesBtn = screen.getByTestId("heatmap-metric-notes");
    fireEvent.click(notesBtn);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(12, undefined, "notes"));

    const tasksBtn = screen.getByTestId("heatmap-metric-tasks");
    fireEvent.click(tasksBtn);
    await waitFor(() => expect(spy).toHaveBeenCalledWith(12, undefined, "tasks"));
  });
});

describe("FocusMetrics (#58, #62)", () => {
  const stub = () => {
    vi.spyOn(api, "activitySwitches").mockResolvedValue({
      day: "2026-10-08",
      switches: 12,
      reasons: { app: 9, gap: 2, project: 1 },
      sessions: 13,
      seconds_per_switch: 1500,
    });
    vi.spyOn(api, "activityCompare").mockResolvedValue({
      day: "2026-10-08",
      seconds: 18000,
      average_seconds: 14400,
      delta_seconds: 3600,
      pct: 25,
      window: 7,
      days_tracked: 5,
    });
  };

  it("shows both numbers", async () => {
    stub();
    render(<FocusMetrics day="2026-10-08" />);
    expect(await screen.findByText("12")).toBeTruthy();
    expect(screen.getByText(/25m each/)).toBeTruthy();
    expect(screen.getByText("+1h")).toBeTruthy();
    expect(screen.getByText(/vs 7-day avg/)).toBeTruthy();
  });

  it("renders a quiet day as a decrease, not a plus", async () => {
    stub();
    vi.spyOn(api, "activityCompare").mockResolvedValue({
      day: "2026-10-08",
      seconds: 7200,
      average_seconds: 14400,
      delta_seconds: -7200,
      pct: -50,
      window: 7,
      days_tracked: 5,
    });
    render(<FocusMetrics day="2026-10-08" />);
    await waitFor(() => expect(screen.getByText("−2h")).toBeTruthy());
  });

  it("disappears when neither metric loads", async () => {
    vi.spyOn(api, "activitySwitches").mockRejectedValue(new Error("offline"));
    vi.spyOn(api, "activityCompare").mockRejectedValue(new Error("offline"));
    const { container } = render(<FocusMetrics day="2026-10-08" />);
    await waitFor(() => expect(api.activityCompare).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});