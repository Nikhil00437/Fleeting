import { describe, expect, it } from "vitest";
import { readingMinutes, tldr, wordCount } from "../noteMeta";

describe("wordCount / readingMinutes", () => {
  it("counts words and tolerates empty text", () => {
    expect(wordCount("")).toBe(0);
    expect(wordCount(null)).toBe(0);
    expect(wordCount("one two three")).toBe(3);
  });

  it("reading time floors at one minute for any text", () => {
    expect(readingMinutes("")).toBe(0);
    expect(readingMinutes("short")).toBe(1);
    expect(readingMinutes("word ".repeat(400))).toBe(2);
  });
});

describe("tldr", () => {
  it("prefers the summary and stops at the first sentence", () => {
    expect(
      tldr({ summary: "First idea. Second thought.", raw_text: "ignored" }),
    ).toBe("First idea.");
  });

  it("falls back to the body and caps the length", () => {
    const long = "x".repeat(300);
    const out = tldr({ raw_text: long });
    expect(out.length).toBeLessThanOrEqual(140);
    expect(out.endsWith("…")).toBe(true);
  });

  it("collapses newlines and returns empty for empty notes", () => {
    expect(tldr({ raw_text: "line one\nline two. more" })).toBe("line one line two.");
    expect(tldr({})).toBe("");
  });
});
