// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import TimelineView from "../TimelineView";
import { api } from "../../api";

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

function setup() {
  vi.spyOn(api, "activityDay").mockResolvedValue({
    day: "2026-10-08",
    paused: false,
    collector: { running: true, enabled: true, last_error: null },
    total_seconds: 0,
    apps: [],
    sessions: [],
  } as never);
  vi.spyOn(api, "activityWeek").mockResolvedValue([]);
  vi.spyOn(api, "activityProjects").mockResolvedValue({ day: "2026-10-08", projects: [] });
  vi.spyOn(api, "activityGaps").mockResolvedValue({ day: "2026-10-08", gaps: [], summary: "" });
  vi.spyOn(api, "activityTimeline").mockResolvedValue({ day: "2026-10-08", events: [] });
  vi.spyOn(api, "liveSession").mockResolvedValue({ session: null, paused: false });
  vi.spyOn(api, "filesActivity").mockResolvedValue({ since: "", total: 0, groups: [], git: [] });
  render(<TimelineView onToast={vi.fn()} refreshKey={0} />);
}

describe("TimelineView export (#342)", () => {
  it("links both exports over the visible range", async () => {
    setup();
    const csv = (await screen.findByLabelText("Export sessions as CSV")) as HTMLAnchorElement;
    expect(csv.getAttribute("href")).toBe("/api/activity/export?format=csv&day_from=2026-10-02&day_to=2026-10-08");
    expect(csv.hasAttribute("download")).toBe(true);

    const sheet = screen.getByLabelText("Export timesheet as CSV") as HTMLAnchorElement;
    expect(sheet.getAttribute("href")).toContain("format=timesheet");
  });

  it("widens the range when a longer one is selected", async () => {
    setup();
    const thirty = (await screen.findByText("30D")) as HTMLButtonElement;
    thirty.click();
    const csv = (await screen.findByLabelText("Export sessions as CSV")) as HTMLAnchorElement;
    expect(csv.getAttribute("href")).toContain("day_from=2026-09-09");
  });
});