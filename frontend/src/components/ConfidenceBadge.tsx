/** #96: how confident the model was in this note's enrichment. */
import { LOW_CONFIDENCE, describeConfidence } from "./noteMeta";
import type { Note } from "../types";

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

/**
 * #263: the sentences of the summary with no source behind them. A title is
 * enough to act on — the drawer shows the claims themselves, because "this
 * sentence might be invented" is only useful if you can read the sentence.
 */
export function UnverifiedClaims({
  claims,
  onToggle,
  expanded,
}: {
  claims: Note["claims"];
  onToggle: () => void;
  expanded: boolean;
}) {
  const bad = (claims ?? []).filter((c) => !c.supported);
  if (!bad.length) return null;
  return (
    <div className="rounded-xl border border-amber-500/25 bg-amber-500/[0.06] p-2.5">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        data-testid="unverified-claims-toggle"
        className="flex w-full items-center gap-1.5 text-left font-mono text-[10px] text-amber-300 transition-colors hover:text-amber-200 cursor-pointer"
      >
        <span className="font-medium">
          {bad.length} unverified {bad.length === 1 ? "claim" : "claims"}
        </span>
        <span className="ml-auto" aria-hidden="true">
          {expanded ? "▲" : "▼"}
        </span>
      </button>
      {expanded && (
        <ul className="mt-1.5 space-y-1">
          {bad.map((c, i) => (
            <li key={`claim-${i}`} className="text-[11px] leading-relaxed text-ink-300">
              {c.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
