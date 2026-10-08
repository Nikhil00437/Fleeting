/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import CaptureFrequencyCard from "../CaptureFrequencyCard";
import { api } from "../../api";
import type { CaptureFrequencyStats } from "../../types";

vi.mock("../../api", () => ({
  api: {
    captureFrequency: vi.fn(),
  },
}));

describe("CaptureFrequencyCard (#163, #168)", () => {
  const mockStats: CaptureFrequencyStats = {
    days: 30,
    total_captures: 42,
    avg_per_day: 1.4,
    busiest_day: { day: "2026-10-07", count: 8 },
    peak_hour: 14,
    notes_per_day: [
      { day: "2026-10-06", count: 3, text: 2, voice: 1, youtube: 0 },
      { day: "2026-10-07", count: 8, text: 5, voice: 2, youtube: 1 },
    ],
    by_dow: [
      { name: "Sun", index: 0, count: 2 },
      { name: "Mon", index: 1, count: 6 },
    ],
    by_hour: [
      { hour: 10, count: 4 },
      { hour: 14, count: 12 },
    ],
    top_tags_over_time: [
      {
        tag: "dev",
        total: 18,
        timeline: [
          { day: "2026-10-06", count: 1 },
          { day: "2026-10-07", count: 4 },
        ],
      },
      {
        tag: "ideas",
        total: 9,
        timeline: [
          { day: "2026-10-06", count: 2 },
          { day: "2026-10-07", count: 1 },
        ],
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.captureFrequency).mockResolvedValue(mockStats);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders capture frequency summary KPIs and tag trends", async () => {
    render(<CaptureFrequencyCard />);

    await waitFor(() => {
      expect(screen.getByText("Capture Frequency & Tag Trends")).toBeDefined();
    });

    expect(screen.getByText("42")).toBeDefined();
    expect(screen.getByText(/1.4/)).toBeDefined();
    expect(screen.getByText("14:00")).toBeDefined();
    expect(screen.getByText(/10-07 \(8\)/)).toBeDefined();
    expect(screen.getByText("#dev")).toBeDefined();
    expect(screen.getByText("#ideas")).toBeDefined();
    expect(screen.getByText("18")).toBeDefined();
  });

  it("updates data when switching time windows", async () => {
    render(<CaptureFrequencyCard />);

    await waitFor(() => {
      expect(api.captureFrequency).toHaveBeenCalledWith(30);
    });

    const btn7d = screen.getByRole("button", { name: "7d" });
    fireEvent.click(btn7d);

    await waitFor(() => {
      expect(api.captureFrequency).toHaveBeenCalledWith(7);
    });
  });
});
