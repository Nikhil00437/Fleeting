/** #263: unverified claims in the summary. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { UnverifiedClaims } from "../ConfidenceBadge";

const claims = [
  { text: "The router runs OpenWrt.", supported: true, span: "The router runs OpenWrt." },
  { text: "We replaced the router in March.", supported: false, span: null },
];

describe("UnverifiedClaims", () => {
  it("renders nothing when every claim is supported", () => {
    expect(
      renderToStaticMarkup(<UnverifiedClaims claims={[claims[0]]} expanded={false} onToggle={() => {}} />),
    ).toBe("");
  });

  it("renders nothing when there are no claims at all", () => {
    expect(
      renderToStaticMarkup(<UnverifiedClaims claims={null} expanded={false} onToggle={() => {}} />),
    ).toBe("");
  });

  it("counts only the unsupported claims", () => {
    const html = renderToStaticMarkup(
      <UnverifiedClaims claims={claims} expanded={false} onToggle={() => {}} />,
    );
    expect(html).toContain("1 unverified claim");
  });

  it("keeps the offending sentences out of the DOM while collapsed", () => {
    const html = renderToStaticMarkup(
      <UnverifiedClaims claims={claims} expanded={false} onToggle={() => {}} />,
    );
    expect(html).not.toContain("replaced the router in March");
  });

  it("shows the offending sentences when expanded", () => {
    const html = renderToStaticMarkup(
      <UnverifiedClaims claims={claims} expanded onToggle={() => {}} />,
    );
    expect(html).toContain("We replaced the router in March.");
  });

  it("never shows a supported sentence as unverified", () => {
    const html = renderToStaticMarkup(
      <UnverifiedClaims claims={claims} expanded onToggle={() => {}} />,
    );
    expect(html).not.toContain("The router runs OpenWrt.");
  });

  it("is a keyboard-reachable disclosure", () => {
    const html = renderToStaticMarkup(
      <UnverifiedClaims claims={claims} expanded={false} onToggle={() => {}} />,
    );
    expect(html).toContain("<button");
    expect(html).toContain('aria-expanded="false"');
  });
});
