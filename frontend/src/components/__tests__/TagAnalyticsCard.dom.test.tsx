/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import TagAnalyticsCard from "../TagAnalyticsCard";
import type { TagGraphData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockTagData: TagGraphData = {
  top_tags: [
    { tag: "python", count: 10 },
    { tag: "fastapi", count: 8 },
    { tag: "sqlite", count: 6 },
  ],
  matrix: [
    [10, 8, 4],
    [8, 8, 3],
    [4, 3, 6],
  ],
  pairs: [
    { tag_a: "python", tag_b: "fastapi", count: 8 },
    { tag_a: "python", tag_b: "sqlite", count: 4 },
    { tag_a: "fastapi", tag_b: "sqlite", count: 3 },
  ],
  weeks: ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"],
  stream: [
    { tag: "python", total_in_window: 10, counts: [2, 3, 3, 2] },
    { tag: "fastapi", total_in_window: 8, counts: [1, 2, 3, 2] },
    { tag: "sqlite", total_in_window: 6, counts: [1, 2, 1, 2] },
  ],
  total_tagged_notes: 15,
};

describe("TagAnalyticsCard (#249)", () => {
  it("renders tag co-occurrence matrix and pairs", async () => {
    vi.spyOn(api, "tagGraph").mockResolvedValue(mockTagData);

    render(<TagAnalyticsCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Tag Co-occurrence & Topic Stream")).toBeDefined();
    });

    expect(screen.getAllByText(/#python/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/#fastapi/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/#sqlite/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Strongest:/)).toBeDefined();
  });

  it("toggles to topic stream view", async () => {
    vi.spyOn(api, "tagGraph").mockResolvedValue(mockTagData);

    render(<TagAnalyticsCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Tag Co-occurrence & Topic Stream")).toBeDefined();
    });

    const streamBtn = screen.getByRole("button", { name: "Topic Stream" });
    fireEvent.click(streamBtn);

    await waitFor(() => {
      expect(screen.getByText("(10)")).toBeDefined(); // Python count in legend
    });
  });

  it("handles empty tag data gracefully", async () => {
    vi.spyOn(api, "tagGraph").mockResolvedValue({
      top_tags: [],
      matrix: [],
      pairs: [],
      weeks: [],
      stream: [],
      total_tagged_notes: 0,
    });

    render(<TagAnalyticsCard refreshKey={0} />);

    await waitFor(() => {
      expect(
        screen.getByText(/No tagged notes available to generate co-occurrence or stream charts/)
      ).toBeDefined();
    });
  });
});
