import { describe, expect, it } from "vitest";
import {
  AUDIO_OP,
  DATE_PRESETS,
  activeDatePreset,
  afterDateForDays,
  applyDatePreset,
  hasOperator,
  toggleOperator,
} from "../searchQuery";

describe("hasOperator", () => {
  it("matches whole tokens only", () => {
    expect(hasOperator("tag:work tag:workflow", "tag:work")).toBe(true);
    expect(hasOperator("tag:workflow", "tag:work")).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(hasOperator("TAG:work", "tag:work")).toBe(true);
  });

  it("handles empty queries", () => {
    expect(hasOperator("", AUDIO_OP)).toBe(false);
  });
});

describe("toggleOperator", () => {
  it("appends a missing operator", () => {
    expect(toggleOperator("router", AUDIO_OP)).toBe("router has:audio");
  });

  it("removes an existing operator", () => {
    expect(toggleOperator("router has:audio", AUDIO_OP)).toBe("router");
  });

  it("toggling twice returns the original query", () => {
    const q = "router type:voice";
    expect(toggleOperator(toggleOperator(q, "tag:work"), "tag:work")).toBe(q);
  });

  it("replaces only the exact token", () => {
    expect(toggleOperator("tag:workflow", "tag:work")).toBe("tag:workflow tag:work");
  });
});

describe("date presets", () => {
  const now = new Date("2026-10-07T12:00:00Z");

  it("computes UTC day strings", () => {
    expect(afterDateForDays(0, now)).toBe("2026-10-07");
    expect(afterDateForDays(7, now)).toBe("2026-09-30");
  });

  it("detects the active preset from the query", () => {
    const q = `router after:${afterDateForDays(7, now)}`;
    expect(activeDatePreset(q, now)).toBe("7d");
    expect(activeDatePreset("router", now)).toBe("any");
  });

  it("applies a preset and rewrites a previously chosen one", () => {
    const seven = DATE_PRESETS.find((p) => p.id === "7d")!;
    const thirty = DATE_PRESETS.find((p) => p.id === "30d")!;
    const with7 = applyDatePreset("router", seven, now);
    expect(with7).toBe(`router after:2026-09-30`);
    const with30 = applyDatePreset(with7, thirty, now);
    expect(with30).toBe(`router after:2026-09-07`);
  });

  it("any removes the date operator", () => {
    const anyPreset = DATE_PRESETS.find((p) => p.id === "any")!;
    const q = `router after:${afterDateForDays(30, now)}`;
    expect(applyDatePreset(q, anyPreset, now)).toBe("router");
  });

  it("stale after: tokens from previous days get rewritten", () => {
    const seven = DATE_PRESETS.find((p) => p.id === "7d")!;
    const q = "router after:2026-01-01";
    // A chip click is a statement about the whole date dimension: the stale
    // token is replaced, not duplicated.
    expect(applyDatePreset(q, seven, now)).toBe(`router after:2026-09-30`);
  });
});
