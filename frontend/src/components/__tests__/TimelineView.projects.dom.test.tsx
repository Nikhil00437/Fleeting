// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import TimelineView from "../TimelineView";
import { api } from "../../api";

const emptyDay = {
  day: "2026-10-08",
  paused: false,
  collector: { running: true, enabled: true, last_error: null },
  total_seconds: 0,
  apps: [],
  sessions: [],
};

// charts.tsx sizes itself with a ResizeObserver, which jsdom does not ship.
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

function stubDay() {
  vi.spyOn(api, "activityDay").mockResolvedValue(emptyDay as never);
  vi.spyOn(api, "activityWeek").mockResolvedValue([]);
  vi.spyOn(api, "liveSession").mockResolvedValue({ session: null, paused: false });
  vi.spyOn(api, "filesActivity").mockResolvedValue({ since: "", total: 0, groups: [], git: [] });
}

describe("TimelineView projects (#53)", () => {
  it("shows time per project", async () => {
    stubDay();
    vi.spyOn(api, "activityProjects").mockResolvedValue({
      day: "2026-10-08",
      projects: [
        { project: "fleeting", seconds: 7200 },
        { project: null, seconds: 300 },
      ],
    });
    render(<TimelineView onToast={() => {}} refreshKey={0} />);

    await waitFor(() => expect(screen.getByText("Projects")).toBeTruthy());
    expect(screen.getByText("fleeting").textContent).toContain("2h");
    expect(screen.getByText("unlabelled").textContent).toContain("5m");
  });

  it("hides the strip when nothing has a project yet", async () => {
    stubDay();
    vi.spyOn(api, "activityProjects").mockResolvedValue({ day: "2026-10-08", projects: [] });
    render(<TimelineView onToast={() => {}} refreshKey={0} />);

    await waitFor(() => expect(api.activityProjects).toHaveBeenCalled());
    expect(screen.queryByText("Projects")).toBeNull();
  });

  it("survives a failed project lookup", async () => {
    stubDay();
    vi.spyOn(api, "activityProjects").mockRejectedValue(new Error("offline"));
    render(<TimelineView onToast={() => {}} refreshKey={0} />);

    await waitFor(() => expect(screen.queryByText("Projects")).toBeNull());
  });
});