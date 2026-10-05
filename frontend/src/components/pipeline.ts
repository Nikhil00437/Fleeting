/**
 * #323: turn a note's pipeline bookkeeping (source.stage / source.timings)
 * into the stepper's view-model. Pure logic lives here so vitest (node env)
 * can pin it without rendering.
 */

export interface Step {
  key: string;
  label: string;
  state: "done" | "current" | "failed" | "todo";
  secs?: number;
}

const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  transcribing: "Transcribing",
  "fetching video": "Fetching",
  enriching: "Enriching",
  syncing: "Syncing",
};

/** Canonical stage order per note type. */
function stagesFor(note: { type: string }): string[] {
  if (note.type === "voice") return ["queued", "transcribing", "enriching", "syncing"];
  if (note.type === "youtube") return ["queued", "fetching video", "enriching", "syncing"];
  return ["queued", "enriching", "syncing"];
}

export function pipelineSteps(note: {
  type: string;
  status: string;
  source?: Record<string, any>;
}): Step[] {
  const src = note.source ?? {};
  const timings: Record<string, number> = src.timings ?? {};
  const current: string | undefined = src.stage;
  const order = stagesFor(note);
  const failed = note.status === "failed";

  // A stage with a recorded timing is done; the current stage has no timing
  // yet; everything after is todo. Notes that predate timings (status
  // pending, no stage data) still render the queued step as current.
  let seenCurrent = false;
  return order.map((key) => {
    const done = note.status === "done" || key in timings;
    const isCurrent =
      !seenCurrent && !done && (key === current || (!current && key === order[0] && note.status !== "done"));
    if (isCurrent) seenCurrent = true;
    let state: Step["state"] = done ? "done" : isCurrent ? (failed ? "failed" : "current") : "todo";
    // queued is implicitly done once the processor has moved on
    if (key === "queued" && note.status === "processing") state = "done";
    return { key, label: STAGE_LABELS[key] ?? key, state, secs: timings[key] };
  });
}

export const totalSecs = (note: { source?: Record<string, any> }): number => {
  const t = (note.source?.timings ?? {}) as Record<string, number>;
  return Math.round(Object.values(t).reduce((a, b) => a + b, 0) * 10) / 10;
};
