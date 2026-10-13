import { describe, expect, it } from "vitest";
import { describeInventory, formatBytes, type InventoryCategory } from "../inventory";

const cat = (over: Partial<InventoryCategory> = {}): InventoryCategory => ({
  name: "notes",
  kind: "table",
  count: 1200,
  count_deleted: null,
  bytes: 4_200_000,
  deletable: true,
  where: "",
  ...over,
});

describe("formatBytes", () => {
  it("reads as a human would", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1024)).toBe("1.0 kB");
    expect(formatBytes(4_200_000)).toBe("4.0 MB");
  });

  it("does not claim a negative size", () => {
    // A negative byte count is nonsense; rendering "-1.0 kB" hides that the
    // number upstream is wrong.
    expect(formatBytes(-5)).toBe("0 B");
  });
});

describe("describeInventory", () => {
  it("leads with the biggest category", () => {
    const line = describeInventory([
      cat({ name: "notes", bytes: 100 }),
      cat({ name: "audio", bytes: 9_000_000 }),
    ]);
    expect(line.indexOf("audio")).toBeLessThan(line.indexOf("notes"));
  });

  it("mentions trashed notes, which are still on disk", () => {
    const line = describeInventory([cat({ count: 5, count_deleted: 3 })]);
    expect(line).toMatch(/3\s*(trashed|deleted)/i);
  });

  it("handles an empty inventory without saying something silly", () => {
    expect(describeInventory([])).toBeTruthy();
  });

  it("marks what you cannot delete by deleting a note", () => {
    const line = describeInventory([cat({ name: "database", deletable: false })]);
    expect(line).toMatch(/database/);
  });
});
