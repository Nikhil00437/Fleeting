/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import RadialDayClock from "../RadialDayClock";
import type { RadialClockData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockRadialData: RadialClockData = {
  day: "2026-10-08",
  total_seconds: 7200,
  daytime_seconds: 5400,
  night_seconds: 1800,
  peak_hour: 14,
  segments: [
    {
      id: 1,
      app_class: "Code",
      project: "Fleeting",
      title: "radial_clock.py",
      seconds: 5400,
      start_time: "14:00",
      end_time: "15:30",
      start_deg: 210.0,
      end_deg: 232.5,
    },
    {
      id: 2,
      app_class: "Firefox",
      project: "Docs",
      title: "MDN Web Docs",
      seconds: 1800,
      start_time: "20:00",
      end_time: "20:30",
      start_deg: 300.0,
      end_deg: 307.5,
    },
  ],
  hourly: Array.from({ length: 24 }).map((_, h) => ({
    hour: h,
    seconds: h === 14 ? 3600 : h === 15 ? 1800 : h === 20 ? 1800 : 0,
    top_app: h === 14 ? "Code" : null,
    top_project: h === 14 ? "Fleeting" : null,
  })),
  apps: [
    { app: "Code", seconds: 5400, pct: 75.0 },
    { app: "Firefox", seconds: 1800, pct: 25.0 },
  ],
  projects: [
    { project: "Fleeting", seconds: 5400, pct: 75.0 },
    { project: "Docs", seconds: 1800, pct: 25.0 },
  ],
};

describe("RadialDayClock (#247)", () => {
  it("renders 24-hour radial clock KPIs, dial, and top apps", async () => {
    vi.spyOn(api, "radialClock").mockResolvedValue(mockRadialData);

    render(<RadialDayClock refreshKey={0} initialDay="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByText("24-Hour Radial Day Clock")).toBeDefined();
    });

    expect(screen.getByText("2h")).toBeDefined(); // 7200s
    expect(screen.getByText("14:00")).toBeDefined(); // Peak hour
    expect(screen.getByText("Code")).toBeDefined();
    expect(screen.getByText("Firefox")).toBeDefined();
    expect(screen.getByText("Active Screentime")).toBeDefined();
  });

  it("toggles color mode between By App and By Project", async () => {
    vi.spyOn(api, "radialClock").mockResolvedValue(mockRadialData);

    render(<RadialDayClock refreshKey={0} initialDay="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByText("24-Hour Radial Day Clock")).toBeDefined();
    });

    const projectBtn = screen.getByRole("button", { name: "By Project" });
    fireEvent.click(projectBtn);

    await waitFor(() => {
      expect(screen.getByText("Top Projects")).toBeDefined();
      expect(screen.getByText("Fleeting")).toBeDefined();
      expect(screen.getByText("Docs")).toBeDefined();
    });
  });

  it("navigates days with Previous and Next buttons", async () => {
    const spy = vi.spyOn(api, "radialClock").mockResolvedValue(mockRadialData);
    const onSelectDay = vi.fn();

    render(
      <RadialDayClock
        refreshKey={0}
        initialDay="2026-10-08"
        onSelectDay={onSelectDay}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("24-Hour Radial Day Clock")).toBeDefined();
    });

    const prevBtn = screen.getByRole("button", { name: "Previous day" });
    fireEvent.click(prevBtn);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith("2026-10-07");
      expect(onSelectDay).toHaveBeenCalledWith("2026-10-07");
    });
  });
});
