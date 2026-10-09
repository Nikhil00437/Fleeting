/** #96 confidence badge and #255 enrichment thumb in the note drawer. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { describeConfidence } from "../noteMeta";
import { ConfidenceBadge } from "../ConfidenceBadge";

describe("describeConfidence", () => {
  it("renders a percentage the model can be trusted with", () => {
    expect(describeConfidence(0.91)).toBe("91% confident");
  });

  it("rounds rather than showing a false precision", () => {
    expect(describeConfidence(0.914)).toBe("91% confident");
  });

  it("treats a missing score as unknown, not as zero", () => {
    expect(describeConfidence(null)).toBeNull();
    expect(describeConfidence(undefined)).toBeNull();
  });

  it("flags a low score as worth checking", () => {
    expect(describeConfidence(0.42)).toBe("42% confident — worth checking");
  });
});

describe("ConfidenceBadge", () => {
  it("shows the percentage", () => {
    const html = renderToStaticMarkup(<ConfidenceBadge confidence={0.91} />);
    expect(html).toContain("91%");
  });

  it("renders nothing when there is no score to show", () => {
    expect(renderToStaticMarkup(<ConfidenceBadge confidence={null} />)).toBe("");
  });

  it("says out loud that the score is the model's own verdict", () => {
    const html = renderToStaticMarkup(<ConfidenceBadge confidence={0.9} />);
    expect(html).toContain("confident");
  });
});
