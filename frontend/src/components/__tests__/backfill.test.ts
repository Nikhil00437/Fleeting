import { describe, expect, it } from "vitest";
import { backfillProgress, describeBackfill } from "../backfill";

describe("backfill progress parsing", () => {
  it("reads done and total", () => {
    expect(backfillProgress({ done: 5, total: 20, model: "nomic-embed-text" })).toEqual({
      done: 5,
      total: 20,
      model: "nomic-embed-text",
      started: false,
      finished: false,
      percent: 25,
    });
  });

  it("flags the started marker", () => {
    expect(backfillProgress({ done: 0, total: 9, started: true }).started).toBe(true);
  });

  it("flags the finished marker", () => {
    expect(backfillProgress({ done: 9, total: 9, finished: true }).finished).toBe(true);
  });

  it("treats a missing total as unknown rather than zero", () => {
    // total=0 would render as "0 of 0" and read as complete.
    const p = backfillProgress({ done: 3 });
    expect(p.total).toBeNull();
  });

  it("tolerates junk", () => {
    expect(backfillProgress(undefined).done).toBe(0);
    expect(backfillProgress({ done: "x" }).done).toBe(0);
  });

  it("never reports done greater than total", () => {
    const p = backfillProgress({ done: 30, total: 20 });
    expect(p.done).toBeLessThanOrEqual(p.total ?? 30);
  });
});

describe("backfill messaging", () => {
  it("describes an idle state", () => {
    expect(describeBackfill(null)).toBe("");
  });

  it("describes progress with a percentage", () => {
    const msg = describeBackfill(backfillProgress({ done: 5, total: 20, started: true, model: "m" }));
    expect(msg).toContain("5");
    expect(msg).toContain("20");
    expect(msg).toContain("%");
  });

  it("describes completion", () => {
    const msg = describeBackfill(backfillProgress({ done: 20, total: 20, started: true, finished: true, model: "m" }));
    expect(msg).toMatch(/20|done|complete/i);
  });

  it("describes completion when total is unknown", () => {
    const msg = describeBackfill(backfillProgress({ done: 7, started: true, finished: true, model: "m" }));
    expect(msg).not.toContain("%");
    expect(msg.length).toBeGreaterThan(0);
  });
});