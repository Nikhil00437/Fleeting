import { describe, expect, it } from "vitest";
import { diffStats, diffText } from "../textDiff";

describe("diffText", () => {
  it("marks unchanged text as same", () => {
    const parts = diffText("hello world", "hello world");
    expect(parts).toEqual([{ type: "same", text: "hello world" }]);
  });

  it("detects an insertion", () => {
    const parts = diffText("hello world", "hello big world");
    expect(parts.filter((p) => p.type === "add").map((p) => p.text.trim())).toEqual(["big"]);
    expect(parts.some((p) => p.type === "same")).toBe(true);
  });

  it("detects a removal", () => {
    const parts = diffText("hello cruel world", "hello world");
    expect(parts.filter((p) => p.type === "del").map((p) => p.text.trim())).toEqual(["cruel"]);
  });

  it("handles full replacement", () => {
    const parts = diffText("abc", "xyz");
    expect(parts.some((p) => p.type === "del")).toBe(true);
    expect(parts.some((p) => p.type === "add")).toBe(true);
  });

  it("degrades past the token cap instead of hanging", () => {
    const big = "word ".repeat(5000);
    const parts = diffText(big, big + " tail");
    expect(parts).toHaveLength(2);
    expect(parts[0].type).toBe("del");
    expect(parts[1].type).toBe("add");
  });

  it("counts changed words for the badge", () => {
    const stats = diffStats(diffText("hello cruel world", "hello big world"));
    expect(stats).toEqual({ added: 1, removed: 1 });
  });
});
