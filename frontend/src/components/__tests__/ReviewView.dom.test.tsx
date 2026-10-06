/**
 * @vitest-environment jsdom
 *
 * #38: the weekly review screen needs its fetch effect to run, so this one
 * cannot be a static-markup test.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import ReviewView from "../ReviewView";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    weeklyReview: vi.fn(),
    updateTask: vi.fn().mockResolvedValue({}),
  },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ReviewView", () => {
  it("offers carry/drop for slipped work and lists what closed", async () => {
    vi.mocked(api.weeklyReview).mockResolvedValue({
      week_start: "2026-10-05",
      today: "2026-10-07",
      carry_over: [
        { id: "c1", text: "finish the proposal", done: false, priority: "P1", due_date: "2026-10-01", created_at: "", completed_at: null, action_items: [], tags: [], note_id: "" },
      ],
      this_week: [],
      completed: [
        { id: "d1", text: "shipped the fix", done: true, priority: "P2", due_date: null, created_at: "", completed_at: "2026-10-06T09:00:00Z", action_items: [], tags: [], note_id: "" },
      ],
      stats: { carry_over: 1, this_week: 0, completed: 1, completion_rate: 0.5 },
    } as never);

    render(<ReviewView onToast={() => {}} />);
    await waitFor(() => expect(screen.getByText("Weekly review")).toBeTruthy());
    expect(screen.getByText("finish the proposal")).toBeTruthy();
    expect(screen.getByText("Carry")).toBeTruthy();
    expect(screen.getByText("Drop")).toBeTruthy();
    expect(screen.getByText("shipped the fix")).toBeTruthy();
  });

  it("carrying a slipped task pushes it to next Monday", async () => {
    vi.mocked(api.weeklyReview).mockResolvedValue({
      week_start: "2026-10-05",
      today: "2026-10-07",
      carry_over: [
        { id: "c1", text: "finish the proposal", done: false, priority: "P1", due_date: "2026-10-01", created_at: "", completed_at: null, action_items: [], tags: [], note_id: "" },
      ],
      this_week: [],
      completed: [],
      stats: { carry_over: 1, this_week: 0, completed: 0, completion_rate: 0 },
    } as never);

    render(<ReviewView onToast={() => {}} />);
    await waitFor(() => expect(screen.getByText("finish the proposal")).toBeTruthy());
    screen.getByText("Carry").click();
    await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith("c1", { due_date: "2026-10-12" }));
  });
});
