/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import TaskFunnelCard from "../TaskFunnelCard";
import BurndownChartCard from "../BurndownChartCard";
import TagAnalyticsCard from "../TagAnalyticsCard";
import RadialDayClock from "../RadialDayClock";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    taskFunnel: vi.fn(),
    burndown: vi.fn(),
    tagGraph: vi.fn(),
    radialClock: vi.fn(),
  },
}));

describe("Chart click-through interactions (#245)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("TaskFunnelCard invokes onSelectStage and onSelectPriority when clicked", async () => {
    const onSelectStage = vi.fn();
    const onSelectPriority = vi.fn();

    (api.taskFunnel as any).mockResolvedValue({
      window_days: 30,
      total_tasks: 10,
      stages: [
        { stage: "captured", name: "Captured", count: 10, pct_of_captured: 100, dropoff_pct: 20 },
        { stage: "planned", name: "Planned", count: 8, pct_of_captured: 80, dropoff_pct: 25 },
        { stage: "started", name: "Started", count: 6, pct_of_captured: 60, dropoff_pct: 33 },
        { stage: "completed", name: "Completed", count: 4, pct_of_captured: 40, dropoff_pct: 0 },
      ],
      by_priority: {
        P1: { captured: 5, completed: 3 },
        P2: { captured: 3, completed: 1 },
        P3: { captured: 2, completed: 0 },
      },
    });

    render(
      <TaskFunnelCard
        refreshKey={1}
        onSelectStage={onSelectStage}
        onSelectPriority={onSelectPriority}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Task Conversion Funnel")).toBeDefined();
    });

    const plannedRow = screen.getByTitle("View tasks in stage: Planned");
    fireEvent.click(plannedRow);
    expect(onSelectStage).toHaveBeenCalledWith("planned");

    const p1Card = screen.getByTitle("View P1 tasks");
    fireEvent.click(p1Card);
    expect(onSelectPriority).toHaveBeenCalledWith("P1");
  });

  it("BurndownChartCard invokes onSelectDay when a bar is clicked", async () => {
    const onSelectDay = vi.fn();

    (api.burndown as any).mockResolvedValue({
      window_days: 30,
      series: [
        {
          day: "2026-10-08",
          unprocessed_inbox: 3,
          open_tasks: 5,
          total_backlog: 8,
          net_change: -1,
        },
      ],
      start_total: 9,
      current_total: 8,
      net_change: -1,
      velocity_per_day: -0.1,
      projected_zero_days: 80,
    });

    const { container } = render(
      <BurndownChartCard refreshKey={1} onSelectDay={onSelectDay} />
    );

    await waitFor(() => {
      expect(screen.getByText("Backlog Burndown")).toBeDefined();
    });

    const rect = container.querySelector("rect[fill='transparent']");
    expect(rect).not.toBeNull();
    if (rect) {
      fireEvent.click(rect);
      expect(onSelectDay).toHaveBeenCalledWith("2026-10-08");
    }
  });

  it("TagAnalyticsCard invokes onSelectTag when a tag header or cell is clicked", async () => {
    const onSelectTag = vi.fn();

    (api.tagGraph as any).mockResolvedValue({
      top_tags: [
        { tag: "work", count: 12 },
        { tag: "project-x", count: 8 },
      ],
      pairs: [{ tag_a: "work", tag_b: "project-x", co_count: 5 }],
      matrix: [[12, 5], [5, 8]],
      weeks: 8,
      stream: [],
    });

    render(<TagAnalyticsCard refreshKey={1} onSelectTag={onSelectTag} />);

    await waitFor(() => {
      expect(screen.getByText("Tag Co-occurrence & Topic Stream")).toBeDefined();
    });

    const tagHeader = screen.getAllByTitle("Filter notes with #work")[0];
    fireEvent.click(tagHeader);
    expect(onSelectTag).toHaveBeenCalledWith("work");
  });

  it("RadialDayClock invokes onSelectApp and onSelectDay when clicked", async () => {
    const onSelectDay = vi.fn();
    const onSelectApp = vi.fn();
    const onSelectProject = vi.fn();

    (api.radialClock as any).mockResolvedValue({
      day: "2026-10-08",
      total_seconds: 7200,
      daytime_seconds: 5400,
      night_seconds: 1800,
      peak_hour: 14,
      segments: [
        {
          id: 1,
          start_time: "14:00",
          end_time: "15:00",
          start_deg: 210,
          end_deg: 225,
          seconds: 3600,
          app_class: "code",
          window_title: "fleeting",
          project: "Fleeting",
        },
      ],
      hourly: Array.from({ length: 24 }).map((_, h) => ({
        hour: h,
        seconds: h === 14 ? 3600 : 0,
      })),
      apps: [{ app: "code", seconds: 7200, pct: 100 }],
      projects: [{ project: "Fleeting", seconds: 7200, pct: 100 }],
    });

    render(
      <RadialDayClock
        refreshKey={1}
        initialDay="2026-10-08"
        onSelectDay={onSelectDay}
        onSelectApp={onSelectApp}
        onSelectProject={onSelectProject}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("24-Hour Radial Day Clock")).toBeDefined();
    });

    const appSidebarItem = screen.getByTitle("Filter by app: code");
    fireEvent.click(appSidebarItem);
    expect(onSelectApp).toHaveBeenCalledWith("code");
  });
});
