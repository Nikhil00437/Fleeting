/** #419: the inbox-zero ritual's arithmetic, extracted so it can be pinned. */
import { describe, expect, it } from "vitest";
import { inboxZeroProgress } from "../inboxZero";

/** Same shape as the ring's inputs: today's notes and how many are filed. */
describe("inbox-zero progress", () => {
  it("counts only today's captures", () => {
    const today = new Date();
    const r = inboxZeroProgress(
      [
        { created_at: today.toISOString(), review_state: "reviewed", status: "done" },
        { created_at: "2020-01-01T00:00:00Z", review_state: "raw", status: "done" },
      ],
      today.setHours(0, 0, 0, 0)
    );
    expect(r.total).toBe(1);
    expect(r.filed).toBe(1);
    expect(r.progress).toBe(1);
  });

  it("an empty day reads as inbox zero reached", () => {
    expect(inboxZeroProgress([], Date.now()).progress).toBe(1);
  });

  it("a processed-but-unreviewed note still counts against the ring", () => {
    const now = new Date();
    const r = inboxZeroProgress(
      [
        { created_at: now.toISOString(), review_state: "raw", status: "done" },
        { created_at: now.toISOString(), review_state: "reviewed", status: "done" },
      ],
      now.setHours(0, 0, 0, 0)
    );
    expect(r.filed).toBe(1);
    expect(r.progress).toBe(0.5);
  });

  it("a shelved note counts as filed", () => {
    const now = new Date();
    const r = inboxZeroProgress(
      [
        { created_at: now.toISOString(), review_state: "raw", status: "done", archived: true },
        { created_at: now.toISOString(), review_state: "raw", status: "done" },
      ],
      now.setHours(0, 0, 0, 0)
    );
    expect(r.filed).toBe(1);
  });
});
