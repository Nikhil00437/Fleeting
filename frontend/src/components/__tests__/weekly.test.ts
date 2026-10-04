import { describe, expect, it } from "vitest";
import { weekLabel, weekProgress } from "../weekly";

describe("week label", () => {
  it("shows the Monday–Sunday range", () => {
    expect(weekLabel("2026-10-05")).toContain("2026-10-05");
    expect(weekLabel("2026-10-05")).toContain("2026-10-11");
  });

  it("names the week for a reader, not just the dates", () => {
    expect(weekLabel("2026-10-05")).toMatch(/week/i);
  });

  it("handles a week spanning two months", () => {
    const label = weekLabel("2026-09-28");
    expect(label).toContain("2026-09-28");
    expect(label).toContain("2026-10-04");
  });

  it("handles a week spanning a year", () => {
    const label = weekLabel("2025-12-29");
    expect(label).toContain("2025-12-29");
    expect(label).toContain("2026-01-04");
  });

  it("returns something for a malformed key rather than throwing", () => {
    expect(weekLabel("not-a-date").length).toBeGreaterThan(0);
  });
});

describe("week progress", () => {
  const days = [
    { day: "2026-10-05", seconds: 7200, busy: true },
    { day: "2026-10-06", seconds: 0, busy: false },
    { day: "2026-10-07", seconds: 3600, busy: true },
    { day: "2026-10-08", seconds: 0, busy: false },
    { day: "2026-10-09", seconds: 1800, busy: true },
    { day: "2026-10-10", seconds: 0, busy: false },
    { day: "2026-10-11", seconds: 0, busy: false },
  ];

  it("counts how many days had real activity", () => {
    expect(weekProgress(days).busyDays).toBe(3);
  });

  it("sums the week's seconds", () => {
    expect(weekProgress(days).totalSeconds).toBe(12600);
  });

  it("finds the busiest day", () => {
    expect(weekProgress(days).busiest).toBe("2026-10-05");
  });

  it("reports no busiest day when nothing happened", () => {
    const idle = days.map((d) => ({ ...d, seconds: 0, busy: false }));
    expect(weekProgress(idle).busiest).toBeNull();
  });

  it("never divides by zero on an idle week", () => {
    const idle = days.map((d) => ({ ...d, seconds: 0, busy: false }));
    const p = weekProgress(idle);
    expect(Number.isFinite(p.averageSeconds)).toBe(true);
    expect(p.averageSeconds).toBe(0);
  });

  it("computes an average across the whole week, not just busy days", () => {
    // 12600 / 7, not 12600 / 3 — a Monday-only user still sees their real week.
    expect(weekProgress(days).averageSeconds).toBe(1800);
  });

  it("handles an empty or malformed day list", () => {
    const p = weekProgress([]);
    expect(p.busyDays).toBe(0);
    expect(p.totalSeconds).toBe(0);
    expect(p.busiest).toBeNull();
    expect(Number.isFinite(p.averageSeconds)).toBe(true);
  });

  it("ignores rows with junk values", () => {
    const messy = [
      { day: "2026-10-05", seconds: 3600, busy: true },
      { day: "2026-10-06", seconds: "nope" as unknown as number, busy: false },
    ];
    const p = weekProgress(messy);
    expect(p.totalSeconds).toBe(3600);
  });
});
