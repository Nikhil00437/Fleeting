import { describe, expect, it } from "vitest";
import { pipelineSteps, totalSecs } from "../pipeline";

describe("pipelineSteps", () => {
  it("fresh text capture shows queued as current", () => {
    const steps = pipelineSteps({ type: "text", status: "pending", source: {} });
    expect(steps.map((s) => [s.key, s.state])).toEqual([
      ["queued", "current"],
      ["enriching", "todo"],
      ["syncing", "todo"],
    ]);
  });

  it("in-flight voice capture marks earlier stages done with timings", () => {
    const steps = pipelineSteps({
      type: "voice",
      status: "processing",
      source: { stage: "enriching", timings: { queued: 0.4, transcribing: 12.3 } },
    });
    expect(steps.find((s) => s.key === "transcribing")).toMatchObject({ state: "done", secs: 12.3 });
    expect(steps.find((s) => s.key === "enriching")).toMatchObject({ state: "current" });
    expect(steps.find((s) => s.key === "syncing")).toMatchObject({ state: "todo" });
  });

  it("failed note paints the active stage red", () => {
    const steps = pipelineSteps({
      type: "voice",
      status: "failed",
      source: { stage: "transcribing", timings: { queued: 0.1 } },
    });
    expect(steps.find((s) => s.key === "transcribing")).toMatchObject({ state: "failed" });
  });

  it("done note is all done and totals sum", () => {
    const note = {
      type: "youtube",
      status: "done",
      source: { timings: { queued: 1, "fetching video": 3, enriching: 2, syncing: 0.5 } },
    };
    expect(pipelineSteps(note).every((s) => s.state === "done")).toBe(true);
    expect(totalSecs(note)).toBe(6.5);
  });
});
