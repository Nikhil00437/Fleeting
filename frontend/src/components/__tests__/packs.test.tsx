import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import PackList from "../PackList";
import { applyTokens, clearTokens, themeStyleText } from "../packs";
import type { Pack } from "../../types";

function pack(over: Partial<Pack> = {}): Pack {
  return {
    name: "Zettel",
    description: "Atomic notes",
    theme: { "--ink-100": "#f0f0f0" },
    prompts: { style_guide: "One idea per note." },
    active: false,
    ...over,
  };
}

describe("applying tokens", () => {
  it("turns tokens into custom property declarations", () => {
    expect(themeStyleText({ "--ink-100": "#fff", "--ember-400": "#f60" })).toBe(
      ":root{--ink-100:#fff;--ember-400:#f60}"
    );
  });

  it("is empty for no tokens", () => {
    expect(themeStyleText({})).toBe("");
  });

  it("returns the properties it set, so they can be reverted", () => {
    // No revert path means no theme can be turned off, which is the state
    // where someone is editing CSS to get their colours back.
    const el = { style: { setProperty: vi.fn(), removeProperty: vi.fn() } };
    const set = applyTokens({ "--ink-100": "#fff" }, el as unknown as HTMLElement);
    expect(el.style.setProperty).toHaveBeenCalledWith("--ink-100", "#fff");
    expect(set).toEqual(["--ink-100"]);
  });

  it("clearing removes exactly what was set", () => {
    // Without this a second pack layers on top of the first and the only way
    // back is the default theme. An inline custom property beats every
    // stylesheet, so nothing else can undo it.
    const el = { style: { setProperty: vi.fn(), removeProperty: vi.fn() } };
    const set = applyTokens({ "--ink-100": "#fff", "--ember-400": "#f60" }, el as unknown as HTMLElement);
    clearTokens(set, el as unknown as HTMLElement);
    expect(el.style.removeProperty).toHaveBeenCalledWith("--ink-100");
    expect(el.style.removeProperty).toHaveBeenCalledWith("--ember-400");
  });
});

describe("PackList", () => {
  it("shows each pack with its description", () => {
    const html = renderToStaticMarkup(<PackList packs={[pack()]} onInstall={() => {}} />);
    expect(html).toContain("Zettel");
    expect(html).toContain("Atomic notes");
  });

  it("marks the installed pack instead of offering to install it again", () => {
    const html = renderToStaticMarkup(
      <PackList packs={[pack({ active: true })]} onInstall={() => {}} />
    );
    expect(html).toMatch(/installed/i);
    // Offering to install the pack that is already installed is how someone
    // ends up clicking a button that re-applies what is already applied.
    expect(html).not.toContain("Install");
  });

  it("offers a button for every pack that is not installed", () => {
    const html = renderToStaticMarkup(<PackList packs={[pack()]} onInstall={() => {}} />);
    expect(html).toContain("<button");
  });

  it("says so when there are no packs, rather than rendering an empty box", () => {
    const html = renderToStaticMarkup(<PackList packs={[]} onInstall={() => {}} />);
    expect(html).toMatch(/no packs/i);
  });

  it("explains where to put one", () => {
    const html = renderToStaticMarkup(<PackList packs={[]} onInstall={() => {}} />);
    expect(html).toContain(".json");
  });

  it("shows why a pack could not be read", () => {
    // Silently omitting it looks identical to never having written the file.
    const html = renderToStaticMarkup(
      <PackList packs={[]} errors={["oops.json: invalid JSON"]} onInstall={() => {}} />
    );
    expect(html).toContain("oops.json");
  });

  it("says when a fetch failed instead of looking empty", () => {
    const html = renderToStaticMarkup(
      <PackList packs={null} error="connection refused" onInstall={() => {}} />
    );
    expect(html).toContain("connection refused");
  });

  it("prompts show which settings the pack will overwrite", () => {
    // Installing overwrites your style guide silently otherwise.
    const html = renderToStaticMarkup(<PackList packs={[pack()]} onInstall={() => {}} />);
    expect(html).toContain("style_guide");
  });
});