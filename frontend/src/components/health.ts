/**
 * #94 health panel wording.
 *
 * Pure per repo convention. The panel is the page you open *because*
 * something is wrong, so every helper here is careful about the difference
 * between "fine" and "nothing to report yet" — those look identical in the
 * raw numbers and mean very different things at 2am.
 */

import type { HealthPanel } from "../types";

export type { HealthPanel };

/** 420 -> "420ms", 2400 -> "2.4s". null -> "—", never "0ms". */
export function formatMs(ms: number | null | undefined): string {
  if (typeof ms !== "number" || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function describeHealth(panel: HealthPanel): string {
  const { llm, embeddings, queue } = panel;
  const parts: string[] = [];

  if (llm.errors > 0) {
    // Leads, because it is the thing to act on.
    parts.push(`${llm.errors} of the last ${llm.calls} calls failed`);
    if (llm.last_error) parts.push(llm.last_error);
  } else if (llm.calls === 0) {
    parts.push("No calls yet");
  } else {
    parts.push(`averaging ${formatMs(llm.avg_ms)}, slowest ${formatMs(llm.max_ms)}`);
  }

  if (embeddings.degraded) {
    parts.push("Semantic search is lexical-only — the embedding provider is unreachable");
  } else if (embeddings.model) {
    parts.push(`${embeddings.indexed} notes embedded with ${embeddings.model}`);
  }

  if (queue.depth >= queue.max) {
    parts.push(`The capture queue is full (${queue.depth}/${queue.max}) — captures are being dropped`);
  } else if (queue.inflight > 0) {
    parts.push(`${queue.inflight} in flight`);
  }

  return parts.join(" · ");
}
