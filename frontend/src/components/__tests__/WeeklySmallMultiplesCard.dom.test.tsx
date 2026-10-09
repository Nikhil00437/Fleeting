/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import WeeklySmallMultiplesCard from "../WeeklySmallMultiplesCard";
import type { WeeklySmallMultiplesData } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockSmallMultiples: WeeklySmallMultiplesData = {
  week_start: "2026-10-05",
  week_end: "2026-10-11",
  total_seconds: 18000,
  avg_daily_seconds: 3600,
  max_hourly_seconds: 3600,
  days: [
    {
      day: "2026-10-05",
      day_of_week: "Mon",
      day_index: 0,
      is_today: false,
      is_future: false,
      total_seconds: 3600,
      focus_score: 70,
      top_app: "Code",
      top_project: "Fleeting",
      hourly: Array.from({ length: 24 }).map((_, h) => (h === 10 ? 3600 : 0)),
    },
    {
      day: "2026-10-06",
      day_of_week: "Tue",
      day_index: 1,
      is_today: false,
      is_future: false,
      total_seconds: 3600,
      focus_score: 85,
      top_app: "Code",
      top_project: "Fleeting",
      hourly: Array.from({ length: 24 }).map((_, h) => (h === 11 ? 3600 : 0)),
    },
    {
      day: "2026-10-07",
      day_of_week: "Wed",
      day_index: 2,
      is_today: false,
      is_future: false,
      total_seconds: 7200,
      focus_score: 90,
      top_app: "Code",
      top_project: "Fleeting",
      hourly: Array.from({ length: 24 }).map((_, h) => (h >= 14 && h <= 15 ? 3600 : 0)),
    },
    {
      day: "2026-10-08",
      day_of_week: "Thu",
      day_index: 3,
      is_today: true,
      is_future: false,
      total_seconds: 3600,
      focus_score: 60,
      top_app: "Firefox",
      top_project: "Docs",
      hourly: Array.from({ length: 24 }).map((_, h) => (h === 16 ? 3600 : 0)),
    },
    {
      day: "2026-10-09",
      day_of_week: "Fri",
      day_index: 4,
      is_today: false,
      is_future: true,
      total_seconds: 0,
      focus_score: 0,
      top_app: null,
      top_project: null,
      hourly: Array(24).fill(0),
    },
    {
      day: "2026-10-10",
      day_of_week: "Sat",
      day_index: 5,
      is_today: false,
      is_future: true,
      total_seconds: 0,
      focus_score: 0,
      top_app: null,
      top_project: null,
      hourly: Array(24).fill(0),
    },
    {
      day: "2026-10-11",
      day_of_week: "Sun",
      day_index: 6,
      is_today: false,
      is_future: true,
      total_seconds: 0,
      focus_score: 0,
      top_app: null,
      top_project: null,
      hourly: Array(24).fill(0),
    },
  ],
};

describe("WeeklySmallMultiplesCard (#248)", () => {
  it("renders all seven days side-by-side with shared scale", async () => {
    vi.spyOn(api, "weeklySmallMultiples").mockResolvedValue(mockSmallMultiples);

    render(<WeeklySmallMultiplesCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Weekly Small-Multiples")).toBeDefined();
    });

    expect(screen.getByText("Mon")).toBeDefined();
    expect(screen.getByText("Tue")).toBeDefined();
    expect(screen.getByText("Wed")).toBeDefined();
    expect(screen.getByText("Thu")).toBeDefined();
    expect(screen.getByText("Fri")).toBeDefined();
    expect(screen.getByText("Sat")).toBeDefined();
    expect(screen.getByText("Sun")).toBeDefined();

    expect(screen.getByText("Week Screentime:")).toBeDefined();
    expect(screen.getByText("Shared scale: 60m max/hr")).toBeDefined();
  });

  it("calls onSelectDay when a day card is clicked", async () => {
    vi.spyOn(api, "weeklySmallMultiples").mockResolvedValue(mockSmallMultiples);
    const onSelectDay = vi.fn();

    render(<WeeklySmallMultiplesCard refreshKey={0} onSelectDay={onSelectDay} />);

    await waitFor(() => {
      expect(screen.getByText("Weekly Small-Multiples")).toBeDefined();
    });

    const wedCard = screen.getByText("Wed");
    fireEvent.click(wedCard);

    expect(onSelectDay).toHaveBeenCalledWith("2026-10-07");
  });

  it("navigates weeks with Prev and Next buttons", async () => {
    const spy = vi.spyOn(api, "weeklySmallMultiples").mockResolvedValue(mockSmallMultiples);

    render(<WeeklySmallMultiplesCard refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Weekly Small-Multiples")).toBeDefined();
    });

    const prevBtn = screen.getByRole("button", { name: "Previous week" });
    fireEvent.click(prevBtn);

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith("2026-09-28");
    });
  });
});
