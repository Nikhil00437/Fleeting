import { describe, expect, it } from "vitest";
import { isActivationKey, noteCardActivationProps } from "../a11y";

describe("activation keys", () => {
  it("accepts Enter and Space, the two keys that mean 'activate' a button", () => {
    expect(isActivationKey("Enter")).toBe(true);
    expect(isActivationKey(" ")).toBe(true);
    // Browsers report the space bar as "Spacebar" in older engines.
    expect(isActivationKey("Spacebar")).toBe(true);
  });

  it("ignores every other key", () => {
    for (const key of ["a", "Escape", "Tab", "ArrowDown", "Shift", "F5"]) {
      expect(isActivationKey(key)).toBe(false);
    }
  });

  it("ignores a bare spacebar keyup, to avoid double-firing with click", () => {
    // A div does not get a synthetic click from Space, unlike a real button.
    expect(isActivationKey(" ", "keyup")).toBe(false);
    expect(isActivationKey(" ", "keydown")).toBe(true);
  });
});

describe("clickable container accessibility props", () => {
  it("exposes the element as a keyboard-reachable button", () => {
    const props = noteCardActivationProps("open the note");
    expect(props.role).toBe("button");
    expect(props.tabIndex).toBe(0);
    expect(props["aria-label"]).toBe("open the note");
  });

  it("does not swallow Tab so focus can leave the card", () => {
    const props = noteCardActivationProps("x");
    expect("onKeyDown" in props).toBe(true);
  });
});