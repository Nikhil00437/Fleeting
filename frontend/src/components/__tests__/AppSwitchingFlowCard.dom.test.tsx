/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import AppSwitchingFlowCard from "../AppSwitchingFlowCard";
import type { AppFlowData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockFlowData: AppFlowData = {
  day: "2026-10-09",
  window_days: 7,
  total_switches: 45,
  nodes: [
    { id: "code", name: "code", incoming: 15, outgoing: 20, seconds: 14000 },
    { id: "google-chrome", name: "google-chrome", incoming: 20, outgoing: 15, seconds: 12000 },
    { id: "kitty", name: "kitty", incoming: 10, outgoing: 10, seconds: 6000 },
  ],
  links: [
    { source: "code", target: "google-chrome", value: 15, pct: 33.3 },
    { source: "google-chrome", target: "code", value: 12, pct: 26.7 },
    { source: "code", target: "kitty", value: 5, pct: 11.1 },
    { source: "kitty", target: "code", value: 8, pct: 17.8 },
  ],
  top_loops: [
    { app_a: "code", app_b: "google-chrome", count: 27 },
    { app_a: "code", app_b: "kitty", count: 13 },
  ],
};

describe("AppSwitchingFlowCard component (#246)", () => {
  it("renders flow KPIs and application nodes", async () => {
    vi.spyOn(api, "activityFlow").mockResolvedValue(mockFlowData);

    render(<AppSwitchingFlowCard refreshKey={0} initialDay="2026-10-09" />);

    await waitFor(() => {
      expect(screen.getByText("App Switching Flow")).toBeTruthy();
    });

    // Check KPIs
    expect(screen.getByText("45")).toBeTruthy(); // total switches
    expect(screen.getByText(/Main Switch Loop/i)).toBeTruthy();

    // Check SVG ribbons
    const svg = document.querySelector("svg");
    expect(svg).toBeTruthy();
    const paths = document.querySelectorAll("path");
    expect(paths.length).toBeGreaterThanOrEqual(4);
  });

  it("switches time window between 1d, 7d and 30d", async () => {
    const flowSpy = vi.spyOn(api, "activityFlow").mockResolvedValue(mockFlowData);

    render(<AppSwitchingFlowCard refreshKey={0} initialDay="2026-10-09" />);

    await waitFor(() => {
      expect(screen.getByText("App Switching Flow")).toBeTruthy();
    });

    const dayBtn = screen.getByRole("button", { name: "1d" });
    fireEvent.click(dayBtn);

    expect(flowSpy).toHaveBeenCalledWith(
      expect.objectContaining({ days: 1 })
    );
  });
});
