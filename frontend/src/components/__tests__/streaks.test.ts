import { describe, expect, it } from "vitest";
import { streakLevel, toWeeks } from "../streaks";

describe("streakLevel", () => {
  it("buckets by completions per day", () => {
    expect(streakLevel(0)).toBe(0);
    expect(streakLevel(1)).toBe(1);
    expect(streakLevel(2)).toBe(1);
    expect(streakLevel(3)).toBe(2);
    expect(streakLevel(5)).toBe(3);
    expect(streakLevel(9)).toBe(4);
  });
});

describe("toWeeks", () => {
  it("chunks flat cells into 7-day columns", () => {
    const cells = Array.from({ length: 14 }, (_, i) => ({ day: `d${i}`, count: 0 }));
    const weeks = toWeeks(cells);
    expect(weeks).toHaveLength(2);
    expect(weeks[0][0].day).toBe("d0");
    expect(weeks[1][6].day).toBe("d13");
  });

  it("keeps a short trailing week", () => {
    const cells = Array.from({ length: 10 }, (_, i) => ({ day: `d${i}`, count: 0 }));
    expect(toWeeks(cells).map((w) => w.length)).toEqual([7, 3]);
  });
});
