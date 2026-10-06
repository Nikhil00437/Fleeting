import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TodayView from "../TodayView";

describe("TodayView streak panel (#39)", () => {
  it("renders the streak counter and heatmap when present", () => {
    const cells = Array.from({ length: 21 }, (_, i) => ({
      day: `2026-10-${String(i + 1).padStart(2, "0")}`,
      count: i === 20 ? 3 : 0,
    }));
    const html = renderToStaticMarkup(
      <TodayView
        refreshKey={0}
        onToast={() => {}}
        initialData={{
          day: "2026-10-21",
          overdue: [],
          due_today: [],
          waiting: [],
          completed_today: [],
          next_action: null,
          up_next: [],
          load: { estimated_min: 0, spent_min: 0, capacity_min: 240 },
          streak: { current_streak: 1, best_streak: 4, active_days: 7, cells },
        }}
      />
    );
    expect(html).toContain("Completion streak");
    expect(html).toContain("day in a row");
    expect(html).toContain("2026-10-21: 3 done");
  });
});
