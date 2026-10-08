// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import TimelineView from "../TimelineView";
import { api } from "../../api";
import type { ActivityDay } from "../../types";

const session = (id: number, title: string) => ({
  id,
  app_class: "kitty",
  title,
  first_seen: `2026-10-08T09:0${id}:00`,
  last_seen: `2026-10-08T09:0${id}:30`,
  seconds: 300,
  day: "2026-10-08",
});

const day = {
  day: "2026-10-08",
  paused: false,
  collector: { running: true, enabled: true, last_error: null },
  total_seconds: 600,
  apps: [{ app: "kitty", seconds: 600, titles: [] }],
  sessions: [session(1, "vim"), session(2, "docs")],
} as unknown as ActivityDay;

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
  const onToast = vi.fn();
  vi.spyOn(api, "activityDay").mockResolvedValue(day);
  vi.spyOn(api, "activityWeek").mockResolvedValue([]);
  vi.spyOn(api, "activityProjects").mockResolvedValue({ day: "2026-10-08", projects: [] });
  vi.spyOn(api, "liveSession").mockResolvedValue({ session: null, paused: false });
  vi.spyOn(api, "filesActivity").mockResolvedValue({ since: "", total: 0, groups: [], git: [] });
  render(<TimelineView onToast={onToast} refreshKey={0} />);
  return { onToast };
}

describe("TimelineView session editing (#54)", () => {
  it("opens the editor from a session row", async () => {
    setup();
    (await screen.findAllByLabelText("Edit kitty session"))[0].click();
    const editor = await screen.findByLabelText("Session editor");
    // the feed is newest-first, so the first row is the 09:02 session
    expect(editor.textContent).toContain("09:02");
  });

  it("merges the selected sessions and reloads", async () => {
    const { onToast } = setup();
    const merge = vi.spyOn(api, "mergeSessions").mockResolvedValue(session(1, "vim") as never);

    (await screen.findAllByLabelText("Select kitty session for merge")).forEach((box) =>
      fireEvent.click(box),
    );
    expect(await screen.findByText("2 picked")).toBeTruthy();

    fireEvent.click(screen.getByText("Merge"));
    await waitFor(() => expect(merge).toHaveBeenCalledWith([1, 2]));
    expect(onToast).toHaveBeenCalledWith("Merged 2 sessions");
  });

  it("clears the selection without touching the API", async () => {
    setup();
    const merge = vi.spyOn(api, "mergeSessions").mockResolvedValue(session(1, "vim") as never);

    (await screen.findAllByLabelText("Select kitty session for merge"))[0].click();
    fireEvent.click(screen.getByLabelText("Clear merge selection"));
    expect(screen.queryByText("1 picked")).toBeNull();
    expect(merge).not.toHaveBeenCalled();
  });

  it("surfaces a rejected merge", async () => {
    const { onToast } = setup();
    vi.spyOn(api, "mergeSessions").mockRejectedValue(new Error("cannot merge sessions from different days"));

    (await screen.findAllByLabelText("Select kitty session for merge")).forEach((box) =>
      fireEvent.click(box),
    );
    fireEvent.click(screen.getByText("Merge"));
    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith("cannot merge sessions from different days", "err"),
    );
  });
});