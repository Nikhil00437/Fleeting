import { describe, expect, it } from "vitest";
import { buildTagTree, flattenTagTree, tagMatches } from "../tagTree";

describe("buildTagTree", () => {
  it("nests slash-separated tags and rolls counts up", () => {
    const tree = buildTagTree([
      { tag: "work", count: 2 },
      { tag: "work/client-a", count: 3 },
      { tag: "work/client-a/billing", count: 1 },
      { tag: "personal", count: 4 },
    ]);
    expect(tree.map((n) => n.name)).toEqual(["personal", "work"]);

    const work = tree[1];
    expect(work.own).toBe(2);
    expect(work.total).toBe(6); // 2 + 3 + 1
    const client = work.children[0];
    expect(client.full).toBe("work/client-a");
    expect(client.total).toBe(4);
    expect(client.children[0].full).toBe("work/client-a/billing");
  });

  it("merges duplicate prefixes across entries", () => {
    const tree = buildTagTree([
      { tag: "a/b", count: 1 },
      { tag: "a/b", count: 2 },
      { tag: "a", count: 1 },
    ]);
    expect(tree).toHaveLength(1);
    expect(tree[0].own).toBe(1);
    expect(tree[0].total).toBe(4);
    expect(tree[0].children[0].own).toBe(3);
  });

  it("tolerates junk paths", () => {
    expect(buildTagTree([{ tag: "", count: 3 }, { tag: "///", count: 2 }])).toEqual([]);
  });
});

describe("tagMatches", () => {
  it("matches exact and descendants only", () => {
    expect(tagMatches("work", "work")).toBe(true);
    expect(tagMatches("work/client-a", "work")).toBe(true);
    expect(tagMatches("workshop", "work")).toBe(false);
    expect(tagMatches("work", null)).toBe(false);
  });
});

describe("flattenTagTree", () => {
  it("yields depth-ordered rows", () => {
    const rows = flattenTagTree(
      buildTagTree([{ tag: "a/b/c", count: 1 }, { tag: "d", count: 2 }]),
    );
    expect(rows.map((r) => `${r.node.full}@${r.depth}`)).toEqual([
      "a@0",
      "a/b@1",
      "a/b/c@2",
      "d@0",
    ]);
  });
});
