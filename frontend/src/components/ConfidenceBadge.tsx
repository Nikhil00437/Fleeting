/** #96: how confident the model was in this note's enrichment. */
import { LOW_CONFIDENCE, describeConfidence } from "./noteMeta";

/**
 * Renders nothing when the score is absent. Heuristic enrichment reports no
 * confidence because deterministic extraction is not uncertain — showing 0%
 * there would read as "the model tried and failed", which is a different and
 * misleading thing.
 */
export function ConfidenceBadge({ confidence }: { confidence: number | null | undefined }) {
  const label = describeConfidence(confidence);
  if (!label || typeof confidence !== "number") return null;
  const low = confidence < LOW_CONFIDENCE;
  return (
    <span
      className={`rounded-md border px-2 py-0.5 font-mono text-[10px] ${
        low
          ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
          : "border-white/[0.06] bg-white/[0.03] text-ink-300"
      }`}
      title="How confident the model was that this title, summary and tags are faithful to the note"
      data-testid="enrich-confidence"
    >
      {label}
    </span>
  );
}
