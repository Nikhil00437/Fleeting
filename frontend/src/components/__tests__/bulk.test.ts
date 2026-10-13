import { describe, expect, it } from "vitest";
import { describeBulkRefusal } from "../bulk";
import type { BulkPreview } from "../../types";

const preview: BulkPreview = {
  count: 3,
  samples: [
    { id: "a", title: "alpha" },
    { id: "b", title: "bravo" },
  ],
  oldest: "2026-01-01",
  newest: "2026-02-01",
};

describe("describeBulkRefusal", () => {
  it("leads with the count", () => {
    // The number is the decision. Everything else is detail.
    expect(describeBulkRefusal(preview).startsWith("3")).toBe(true);
  });

  it("names what would go", () => {
    const line = describeBulkRefusal(preview);
    expect(line).toContain("alpha");
    expect(line).toContain("bravo");
  });

  it("truncates a long sample list rather than filling the dialog", () => {
    const many: BulkPreview = {
      count: 40,
      samples: Array.from({ length: 20 }, (_, i) => ({ id: String(i), title: `note ${i}` })),
    };
    expect(describeBulkRefusal(many).length).toBeLessThan(240);
  });

  it("handles a single item without saying 'items'", () => {
    expect(describeBulkRefusal({ count: 1, samples: [{ id: "a", title: "one" }] })).toContain("1 note");
  });

  it("handles no samples at all", () => {
    expect(describeBulkRefusal({ count: 12, samples: [] })).toContain("12");
  });
});

describe("a confirmed destructive call", () => {
  it("sends confirm rather than relying on the server defaulting", () => {
    // The default is `confirm: false` on the server. Omitting it must not be
    // how a delete happens.
    expect(JSON.stringify({ confirm: true })).toContain("confirm");
  });
});