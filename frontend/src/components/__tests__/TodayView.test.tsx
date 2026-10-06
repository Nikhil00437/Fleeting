import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TodayView from "../TodayView";
import type { TodayData } from "../../types";

vi.mock("../../api", () => ({
  api: {
    today: vi.fn(),
    toggleTask: vi.fn(),
    updateTask: vi.fn(),
  },
}));

const data: TodayData = {
  day: "2026-10-07",
  overdue: [
    {
      id: "t1", note_id: "n1", text: "overdue task", done: false, priority: "P1",
      due_date: "2026-10-05", repo: null, created_at: "", completed_at: null,
    },
  ],
  due_today: [
    {
      id: "t2", note_id: "n1", text: "due task", done: false, priority: "P2",
      due_date: "2026-10-07", repo: "fleeting", created_at: "", completed_at: null,
      estimate_min: 30, context: "computer",
    },
  ],
  waiting: [
    {
      id: "t3", note_id: "n1", text: "waiting task", done: false, priority: "P2",
      due_date: null, repo: null, created_at: "", completed_at: null, waiting_for: "bob",
    },
  ],
  completed_today: [
    {
      id: "t4", note_id: "n1", text: "finished task", done: true, priority: "P3",
      due_date: null, repo: null, created_at: "", completed_at: "2026-10-07T09:00:00Z",
    },
  ],
  next_action: {
    id: "t1", note_id: "n1", text: "overdue task", done: false, priority: "P1",
    due_date: "2026-10-05", repo: null, created_at: "", completed_at: null,
  },
  up_next: [],
  load: { estimated_min: 90, spent_min: 25, capacity_min: 240 },
};

function render(d: TodayData = data) {
  return renderToStaticMarkup(<TodayView refreshKey={0} onToast={() => {}} initialData={d} />);
}

describe("TodayView", () => {
  it("renders the next-action hero card", () => {
    const html = render();
    expect(html).toContain("Do this now");
    expect(html).toContain("overdue task");
  });

  it("renders overdue, due-today and completed buckets", () => {
    const html = render();
    expect(html).toContain("Overdue");
    expect(html).toContain("due task");
    expect(html).toContain("Done today (1)");
    expect(html).toContain("Waiting for");
  });

  it("renders the day-load meter with capacity", () => {
    const html = render();
    expect(html).toContain("Day load");
    expect(html).toContain("1.5h planned / 4h capacity");
    expect(html).toContain("aria-valuenow=\"90\"");
  });

  it("explains an empty day", () => {
    expect(render({
      ...data, next_action: null, overdue: [], due_today: [], up_next: [],
      waiting: [], completed_today: [],
    })).toContain("Nothing queued");
  });
});
