/**
 * #446 / #447 / #261 the writing menu.
 *
 * Four APIs have shipped with no surface at all: rewrite, title suggestions,
 * transcript cleanup and style guide. This is the one place that reaches them.
 *
 * Nothing is applied automatically. Every result is offered with Accept and
 * Discard, because a rewrite the user did not accept must not have replaced
 * their words — that rule is the backend's, and a button that auto-saved would
 * quietly break it.
 *
 * Node environment on purpose: it renders to static markup, so the behaviour
 * under test is what is shown, not the click handlers.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WritingMenu } from "../WritingMenu";
import type { RewriteStyle, WritingResult } from "../../types";

function render(props: Partial<Parameters<typeof WritingMenu>[0]> = {}) {
  return renderToStaticMarkup(
    <WritingMenu
      text="um so i was thinking we should move the standup to tuesdays you know"
      result={null}
      onApply={() => {}}
      onToast={() => {}}
      {...props}
    />,
  );
}

describe("WritingMenu", () => {
  it("offers the rewrite styles the service accepts", () => {
    const html = render({ styles: ["shorter", "clearer", "friendlier", "more formal"] });
    expect(html).toContain("Shorter");
    expect(html).toContain("Clearer");
    expect(html).toContain("Friendlier");
    expect(html).toContain("More formal");
  });

  it("offers dictated-text cleanup, which is a different thing", () => {
    expect(render()).toContain("Clean up");
  });

  it("does nothing without text to work on", () => {
    const html = render({ text: "" });
    expect(html).toMatch(/nothing|select|choose/i);
  });

  it("offers the result for acceptance rather than applying it", () => {
    const result: WritingResult = {
      text: "So I was thinking we should move the standup to Tuesdays.",
      style: "clearer",
      kept_wording: true,
      added_words: [],
    };
    const html = render({ result });
    expect(html).toContain("So I was thinking");
    expect(html).toContain("Accept");
    expect(html).toContain("Discard");
  });

  it("warns when the model invented words rather than hiding it", () => {
    // #261: the whole point of keep-wording is that a reword is reported, not
    // quietly applied. A silent result would defeat the feature.
    const html = render({
      result: {
        text: "I should probably consider calling the dentist.",
        style: "cleaner",
        kept_wording: false,
        added_words: ["consider", "probably"],
      },
    });
    expect(html).toContain("consider");
    expect(html.toLowerCase()).toContain("added");
  });

  it("shows an error rather than pretending a rewrite failed silently", () => {
    expect(render({ error: "model unavailable" })).toContain("model unavailable");
  });

  it("does not show a result and an error at once", () => {
    const html = render({
      result: { text: "x", style: "shorter", kept_wording: true, added_words: [] },
      error: "boom",
    });
    expect(html).not.toContain("Accept");
  });

  it("offers title suggestions when asked", () => {
    const html = render({ titles: ["A", "B", "C"], showTitles: true });
    expect(html).toContain("A");
    expect(html).toContain("C");
  });
});

export type { RewriteStyle };