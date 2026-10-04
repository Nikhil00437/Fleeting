/** Progress state for the embedding migration.
 *
 * Turning the LLM on changes the embedding dimensionality, so every note
 * captured beforehand stops matching. The backend migrates them in the
 * background; a 5000-note corpus is 5000 HTTP calls, so it has to show
 * progress or it looks like the app has hung.
 */

export interface BackfillPayload {
  done: number;
  /** null when the backend did not say, so the UI must not render "0 of 0". */
  total: number | null;
  model: string | null;
  started: boolean;
  finished: boolean;
}

export interface BackfillState extends BackfillPayload {
  /** 0-100, or null when the total is unknown. */
  percent: number | null;
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0;
}

/** Normalise one `embedding.backfill.progress` payload. */
export function backfillProgress(data: unknown): BackfillState {
  const d = (typeof data === "object" && data !== null ? data : {}) as Record<string, unknown>;
  const done = num(d.done);
  const rawTotal = d.total;
  const total =
    typeof rawTotal === "number" && Number.isFinite(rawTotal) && rawTotal > 0
      ? Math.floor(rawTotal)
      : null;
  // Clamp: a mismatched count must not overflow the bar or read as >100%.
  const clamped = total === null ? done : Math.min(done, total);
  return {
    done: clamped,
    total,
    model: typeof d.model === "string" ? d.model : null,
    started: d.started === true,
    finished: d.finished === true,
    percent: total ? Math.min(100, Math.round((clamped / total) * 100)) : null,
  };
}

/** One line for the settings panel; empty string means "nothing to say". */
export function describeBackfill(state: BackfillState | null): string {
  if (!state) return "";
  if (state.finished) {
    const n = state.total ?? state.done;
    return n === 1
      ? "Re-embedded 1 note for semantic search."
      : `Re-embedded ${n} notes for semantic search.`;
  }
  if (state.started || state.done > 0) {
    if (state.percent === null) {
      return `Re-embedding notes for semantic search — ${state.done} done…`;
    }
    return `Re-embedding notes for semantic search — ${state.done}/${state.total} (${state.percent}%)`;
  }
  return "";
}
