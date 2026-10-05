import { describe, expect, it } from "vitest";
import { canSignal, killBlockedReason } from "../processOwnership";

describe("canSignal", () => {
  it("allows your own processes", () => {
    expect(canSignal({ username: "nikhil" }, "nikhil")).toBe(true);
  });

  it("refuses another user's process", () => {
    expect(canSignal({ username: "root" }, "nikhil")).toBe(false);
  });

  it("refuses when the owner is unknown", () => {
    // Unknown owner must not be assumed signalable.
    expect(canSignal({}, "nikhil")).toBe(false);
    expect(canSignal({ username: "" }, "nikhil")).toBe(false);
  });

  it("survives a null process row", () => {
    expect(canSignal(null, "nikhil")).toBe(false);
  });

  it("never throws when the current user is unknown", () => {
    expect(canSignal({ username: "root" }, "")).toBe(false);
  });
});

describe("killBlockedReason", () => {
  it("is empty when the process can be ended", () => {
    expect(killBlockedReason({ username: "nikhil" }, "nikhil")).toBe("");
  });

  it("names the owner, since 'Access denied' explains nothing", () => {
    const why = killBlockedReason({ username: "root" }, "nikhil");
    expect(why).toContain("root");
    expect(why).toMatch(/cannot|not permitted|permission/i);
  });

  it("says who you are, so the limit is obvious", () => {
    expect(killBlockedReason({ username: "root" }, "nikhil")).toContain("nikhil");
  });

  it("handles a missing owner without printing undefined", () => {
    const why = killBlockedReason({}, "nikhil");
    expect(why).not.toContain("undefined");
    expect(why.length).toBeGreaterThan(10);
  });

  it("is empty for a null row rather than crashing the row render", () => {
    expect(typeof killBlockedReason(null, "nikhil")).toBe("string");
  });
});
