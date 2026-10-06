/**
 * @vitest-environment jsdom
 *
 * #279: dropping a task on a day column writes that due date.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import PlannerView from "../PlannerView";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    weekPlan: vi.fn(),
    tasks: vi.fn(),
    updateTask: vi.fn().mockResolvedValue({}),
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function setup() {
  vi.mocked(api.weekPlan).mockResolvedValue({
    week_start: "2026-10-05",
    days: [
      { day: "2026-10-05", workday: true, capacity_min: 240, planned_min: 60, task_ids: [] },
      { day: "2026-10-06", workday: true, capacity_min: 240, planned_min: 0, task_ids: [] },
    ],
    unscheduled: ["u1"],
    totals: { capacity_min: 480, planned_min: 60, over_capacity: false, utilization: 0.125 },
  } as never);
  vi.mocked(api.tasks).mockResolvedValue([
    {
      id: "u1",
      text: "write the RFC",
      done: false,
      priority: "P2",
      due_date: null,
      created_at: "",
      completed_at: null,
      note_id: "",
      tags: [],
      action_items: [],
    },
  ] as never);
}

describe("PlannerView", () => {
  it("shows the capacity gauge and the unplanned tray", async () => {
    setup();
    render(<PlannerView />);
    await waitFor(() => expect(screen.getByText("Week of 2026-10-05")).toBeTruthy());
    expect(screen.getByText("write the RFC")).toBeTruthy();
    expect(screen.getByText(/1h planned of 8h/)).toBeTruthy();
  });

  it("dropping a task on a day sets its due date", async () => {
    setup();
    const { container } = render(<PlannerView />);
    await waitFor(() => expect(screen.getByText("write the RFC")).toBeTruthy());
    const columns = container.querySelectorAll(".glass");
    const monday = columns[0] as HTMLElement;
    fireEvent.drop(monday, { dataTransfer: { getData: () => "u1" } });
    await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith("u1", { due_date: "2026-10-05" }));
  });
});
