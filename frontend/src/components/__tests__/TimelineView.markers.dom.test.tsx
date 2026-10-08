// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import TimelineView from "../TimelineView";
import { api } from "../../api";
import type { ActivityDay, DayEvent } from "../../types";

const day = {
  day: "2026-10-08",
  paused: false,
  collector: { running: true, enabled: true, last_error: null },
  total_seconds: 600,
  apps: [{ app: "kitty", seconds: 600, titles: [] }],
  sessions: [],
} as unknown as ActivityDay;

const event = (over: Partial<DayEvent> = {}): DayEvent => ({
  kind: "note",
  id: "n1",
  at: "2026-10-08T11:30:00",
  label: "meeting notes",
  ...over,
});

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
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

function setup(events: DayEvent[], handlers: { onOpenNote?: (id: string) => void; onToast?: (m: string) => void } = {}) {
  vi.spyOn(api, "activityDay").mockResolvedValue(day);
  vi.spyOn(api, "activityWeek").mockResolvedValue([]);
  vi.spyOn(api, "activityProjects").mockResolvedValue({ day: "2026-10-08", projects: [] });
  vi.spyOn(api, "activityGaps").mockResolvedValue({ day: "2026-10-08", gaps: [], summary: "" });
  vi.spyOn(api, "activityTimeline").mockResolvedValue({ day: "2026-10-08", events });
  vi.spyOn(api, "liveSession").mockResolvedValue({ session: null, paused: false });
  vi.spyOn(api, "filesActivity").mockResolvedValue({ since: "", total: 0, groups: [], git: [] });
  render(<TimelineView onToast={handlers.onToast ?? vi.fn()} refreshKey={0} onOpenNote={handlers.onOpenNote} />);
}

describe("TimelineView ribbon markers (#339)", () => {
  it("pins notes and tasks to their hour on the ribbon", async () => {
    setup([
      event({ id: "n1", label: "meeting notes" }),
      event({ kind: "task", id: "t1", label: "ship it", at: "2026-10-08T15:00:00" }),
    ]);

    const note = await screen.findByLabelText(/^note: meeting notes at /);
    // 11:30 of 24h down the ribbon
    expect(note.getAttribute("style")).toContain("47.9166");
    expect(await screen.findByLabelText(/^task: ship it at /)).toBeTruthy();
  });

  it("asks the backend for task and note markers only", async () => {
    setup([]);
    expect(api.activityTimeline).toHaveBeenCalledWith("2026-10-08", "task,note");
  });

  it("opens the note when its marker is clicked", async () => {
    const onOpenNote = vi.fn();
    setup([event({ id: "n7", label: "router plan" })], { onOpenNote });

    fireEvent.click(await screen.findByLabelText(/^note: router plan at /));
    expect(onOpenNote).toHaveBeenCalledWith("n7");
  });

  it("reports a task marker as a toast, since a task has nowhere to open", async () => {
    const onToast = vi.fn();
    setup([event({ kind: "task", id: "t9", label: "ship it" })], { onToast });

    fireEvent.click(await screen.findByLabelText(/^task: ship it at /));
    expect(onToast).toHaveBeenCalledWith("finished task: ship it");
  });

  it("renders no markers when the day has none", async () => {
    setup([]);
    await screen.findByText("No tracked sessions for this day");
    expect(document.querySelectorAll('[aria-label^="note:"], [aria-label^="task:"]')).toHaveLength(0);
  });
});