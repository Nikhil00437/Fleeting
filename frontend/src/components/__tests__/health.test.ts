/**
 * #94 health panel formatting.
 *
 * Pure per repo convention: the panel is the page you open when something is
 * wrong, and "nothing here yet" must not read as "everything is fine".
 */
import { describe, expect, it } from "vitest";

import { describeHealth, formatMs } from "../health";

describe("formatMs", () => {
  it("renders sub-second times in ms", () => {
    expect(formatMs(420)).toBe("420ms");
  });

  it("renders slow calls in seconds", () => {
    expect(formatMs(2400)).toBe("2.4s");
  });

  it("says unknown rather than 0ms", () => {
    // 0ms reads as "instantly fast", which is a claim, not a measurement.
    expect(formatMs(null)).toBe("—");
    expect(formatMs(undefined)).toBe("—");
  });
});

describe("describeHealth", () => {
  const fine = {
    llm: { calls: 12, avg_ms: 420, max_ms: 900, errors: 0, last_error: null },
    embeddings: {
      model: "nomic-embed-text",
      degraded: false,
      dimensions: 384,
      indexed: 210,
      detail: "",
    },
    queue: { depth: 0, max: 500, inflight: 0, running: true },
  };

  it("summarises latency when calls have happened", () => {
    const out = describeHealth(fine);
    expect(out).toContain("420ms");
  });

  it("says so when there are no calls yet", () => {
    const out = describeHealth({ ...fine, llm: { ...fine.llm, calls: 0, avg_ms: null } });
    expect(out.toLowerCase()).toContain("no calls yet");
  });

  it("leads with the error when one happened", () => {
    const out = describeHealth({
      ...fine,
      llm: { ...fine.llm, errors: 3, last_error: "ConnectError: refused" },
    });
    // The denominator matters: 3 of 12 reads very differently from 3 of 3.
    expect(out).toContain("3 of the last 12 calls failed");
    expect(out).toContain("ConnectError");
  });

  it("warns loudly about a degraded embedding index", () => {
    const out = describeHealth({
      ...fine,
      embeddings: { ...fine.embeddings, degraded: true, model: "local-hash-384" },
    });
    expect(out).toMatch(/lexical/i);
  });

  it("mentions a full queue", () => {
    const out = describeHealth({
      ...fine,
      queue: { depth: 500, max: 500, inflight: 2, running: true },
    });
    expect(out).toMatch(/queue is full/i);
  });

  it("mentions work in flight", () => {
    const out = describeHealth({ ...fine, queue: { ...fine.queue, inflight: 1 } });
    expect(out).toMatch(/1 in flight/i);
  });

  it("says nothing alarming when everything is fine", () => {
    const out = describeHealth(fine);
    expect(out).not.toMatch(/lexical|failed|full/i);
  });
});
