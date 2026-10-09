/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import ProjectTreemapCard, { squarify } from "../ProjectTreemapCard";
import type { ProjectTreemapData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockTreemapData: ProjectTreemapData = {
  window_days: 7,
  day: null,
  total_seconds: 7200,
  project_count: 2,
  projects: [
    {
      name: "Fleeting",
      seconds: 5400,
      pct: 75.0,
      apps: [
        { name: "Code", seconds: 3600, pct_of_project: 66.7, pct_of_total: 50.0 },
        { name: "Terminal", seconds: 1800, pct_of_project: 33.3, pct_of_total: 25.0 },
      ],
    },
    {
      name: "Docs",
      seconds: 1800,
      pct: 25.0,
      apps: [
        { name: "Firefox", seconds: 1800, pct_of_project: 100.0, pct_of_total: 25.0 },
      ],
    },
  ],
};

describe("ProjectTreemapCard (#251)", () => {
  it("squarify algorithm partitions area properly", () => {
    const items = [
      { name: "A", seconds: 60 },
      { name: "B", seconds: 40 },
    ];
    const rects = squarify(items, { x: 0, y: 0, w: 100, h: 100 });
    expect(rects.length).toBe(2);
    expect(rects[0].w * rects[0].h + rects[1].w * rects[1].h).toBeCloseTo(10000);
  });

  it("renders treemap projects and application boxes", async () => {
    vi.spyOn(api, "projectTreemap").mockResolvedValue(mockTreemapData);

    render(<ProjectTreemapCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Project Time Treemap")).toBeDefined();
    });

    expect(screen.getAllByText(/Fleeting/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Docs/).length).toBeGreaterThan(0);
    expect(screen.getByText("Total tracked:")).toBeDefined();
    expect(screen.getByText("Active projects:")).toBeDefined();
  });

  it("changes window filter when clicked", async () => {
    const spy = vi.spyOn(api, "projectTreemap").mockResolvedValue(mockTreemapData);

    render(<ProjectTreemapCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Project Time Treemap")).toBeDefined();
    });

    const btn30d = screen.getByRole("button", { name: "30d" });
    fireEvent.click(btn30d);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ days: 30 });
    });
  });

  it("calls onSelectProject when project pill is clicked", async () => {
    vi.spyOn(api, "projectTreemap").mockResolvedValue(mockTreemapData);
    const onSelect = vi.fn();

    render(<ProjectTreemapCard refreshKey={0} onSelectProject={onSelect} />);

    await waitFor(() => {
      expect(screen.getByText("Project Time Treemap")).toBeDefined();
    });

    const pill = screen.getByRole("button", { name: /Fleeting \(75%\)/ });
    fireEvent.click(pill);

    expect(onSelect).toHaveBeenCalledWith("Fleeting");
  });

  it("renders empty state gracefully", async () => {
    vi.spyOn(api, "projectTreemap").mockResolvedValue({
      window_days: 7,
      day: null,
      total_seconds: 0,
      project_count: 0,
      projects: [],
    });

    render(<ProjectTreemapCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("No project activity recorded for this period.")).toBeDefined();
    });
  });
});
