import { describe, expect, it } from "vitest";
import { bucketCounts, emptyUnified, sessionLabel } from "../unifiedSearch";

describe("emptyUnified", () => {
  it("always has every bucket, so the UI can index without null checks", () => {
    const u = emptyUnified();
    expect(u.notes).toEqual([]);
    expect(u.sessions).toEqual([]);
    expect(u.commits).toEqual([]);
    expect(u.counts).toEqual({ notes: 0, sessions: 0, commits: 0 });
    expect(u.total).toBe(0);
  });
});

describe("bucketCounts", () => {
  const unified = {
    notes: [{ id: "a" }, { id: "b" }],
    sessions: [{ id: 1 }],
    commits: [{ repo: "r", subject: "s" }],
    counts: { notes: 2, sessions: 1, commits: 1 },
    total: 4,
  };

  it("returns the count for each bucket", () => {
    expect(bucketCounts(unified)).toEqual([
      { key: "notes", label: "Notes", count: 2 },
      { key: "sessions", label: "Windows", count: 1 },
      { key: "commits", label: "Commits", count: 1 },
    ]);
  });

  it("prefers the server's counts when present", () => {
    const withServer = { ...unified, notes: [], counts: { notes: 7, sessions: 0, commits: 0 } };
    const rows = bucketCounts(withServer);
    expect(rows.find((r) => r.key === "notes")?.count).toBe(7);
  });

  it("falls back to counting the arrays when counts are missing", () => {
    const noCounts = { ...unified, counts: undefined };
    expect(bucketCounts(noCounts).find((r) => r.key === "notes")?.count).toBe(2);
  });

  it("survives a null response", () => {
    expect(bucketCounts(null)).toHaveLength(3);
  });
});

describe("sessionLabel", () => {
  it("names the app and says how long", () => {
    expect(sessionLabel({ app_class: "code", title: "x", day: "2026-10-04", seconds: 3600 })).toContain(
      "1h",
    );
  });

  it("falls back to the window title when the app is unknown", () => {
    const label = sessionLabel({
      app_class: "",
      title: "reading docs",
      day: "2026-10-04",
      seconds: 60,
    });
    expect(label).toContain("reading docs");
  });

  it("never returns an empty label", () => {
    const label = sessionLabel({
      app_class: "",
      title: "",
      day: "2026-10-04",
      seconds: 0,
    });
    expect(label.length).toBeGreaterThan(0);
  });
});
