import { describe, expect, it } from "vitest";
import { dayLabel, groupNotes } from "../grouping";
import type { Note } from "../../types";

const note = (id: string, over: Partial<Note> = {}): Note =>
  ({
    id,
    type: "text",
    title: id,
    summary: "",
    raw_text: "",
    tags: [],
    action_items: [],
    source: {},
    audio_path: null,
    status: "done",
    error: null,
    pinned: false,
    archived: false,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    processed_at: null,
    ...over,
  }) as Note;

const NOW = new Date("2026-10-08T12:00:00Z");

describe("dayLabel", () => {
  it("names today and yesterday", () => {
    expect(dayLabel("2026-10-08T09:00:00Z", NOW)).toBe("Today");
    expect(dayLabel("2026-10-07T09:00:00Z", NOW)).toBe("Yesterday");
  });

  it("uses the weekday within the last week, a date beyond that", () => {
    expect(dayLabel("2026-10-04T09:00:00Z", NOW)).toMatch(/^(Sunday|Monday)$/);
    expect(dayLabel("2026-09-01T09:00:00Z", NOW)).toMatch(/Sep/);
  });

  it("survives a missing timestamp", () => {
    expect(dayLabel("", NOW)).toBe("undated");
  });
});

describe("groupNotes", () => {
  it("returns one bucket when grouping is off", () => {
    const out = groupNotes([note("a"), note("b")], "none", NOW);
    expect(out).toHaveLength(1);
    expect(out[0].items).toHaveLength(2);
  });

  it("returns nothing for an empty list", () => {
    expect(groupNotes([], "day", NOW)).toEqual([]);
  });

  it("buckets by day, newest first", () => {
    const out = groupNotes(
      [note("a", { created_at: "2026-10-05T09:00:00Z" }), note("b", { created_at: "2026-10-07T09:00:00Z" })],
      "day",
      NOW,
    );
    expect(out.map((g) => g.key)).toEqual(["2026-10-07", "2026-10-05"]);
    expect(out[0].label).toBe("Yesterday");
  });

  it("lists a note under each of its tags", () => {
    const out = groupNotes([note("a", { tags: ["work", "router"] })], "tag", NOW);
    expect(out.map((g) => g.key).sort()).toEqual(["router", "work"]);
    expect(out.every((g) => g.items[0].id === "a")).toBe(true);
  });

  it("collects untagged notes under one bucket", () => {
    const out = groupNotes([note("a"), note("b", { tags: ["x"] })], "tag", NOW);
    expect(out.find((g) => g.key === "untagged")?.items.map((n) => n.id)).toEqual(["a"]);
    expect(out.find((g) => g.key === "x")?.label).toBe("#x");
  });

  it("buckets by repo and files the rest under 'no project'", () => {
    const out = groupNotes([note("a", { source: { repo: "fleeting" } }), note("b")], "project", NOW);
    expect(out.map((g) => g.key).sort()).toEqual(["fleeting", "no project"]);
    expect(out[0].key === "fleeting" ? out[0].items[0].id : out[1].items[0].id).toBe("a");
  });
});