import { describe, expect, it } from "vitest";
import { normalizeTag } from "../tagTree";

/** #420: triage's tag action normalises what the user typed. */
describe("normalizeTag", () => {
  it("strips a leading hash and lowercases", () => {
    expect(normalizeTag("  #Health ")).toBe("health");
    expect(normalizeTag("Work")).toBe("work");
  });

  it("rejects empty input", () => {
    expect(normalizeTag("   ")).toBe("");
    expect(normalizeTag("#")).toBe("");
  });
});
