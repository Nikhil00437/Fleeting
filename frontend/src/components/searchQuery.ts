/**
 * Chip ⇄ operator-query translation for the search toolbar (#41, #313).
 *
 * Filter chips don't get their own request params — they append/remove
 * operator tokens in the query box, so a chip click and a hand-typed
 * `tag:work` are the same thing to the backend's single parser. Pure logic
 * lives here (not in the component) so tests can run with the SSR-string
 * renderer, same pattern as unifiedSearch.ts.
 */

export interface DatePreset {
  id: string;
  label: string;
  /** Days back from today; null = "any time" (no operator). */
  days: number | null;
}

export const DATE_PRESETS: DatePreset[] = [
  { id: "any", label: "Any time", days: null },
  { id: "today", label: "Today", days: 0 },
  { id: "7d", label: "7 days", days: 7 },
  { id: "30d", label: "30 days", days: 30 },
  { id: "90d", label: "90 days", days: 90 },
];

export const AUDIO_OP = "has:audio";

/** UTC day string (YYYY-MM-DD) N days before now — the parser's date form. */
export function afterDateForDays(days: number, now: Date = new Date()): string {
  const d = new Date(now.getTime());
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Whole-token match, so `tag:work` doesn't light up for `tag:workflow`. */
export function hasOperator(query: string, op: string): boolean {
  const needle = op.toLowerCase();
  return query
    .split(/\s+/)
    .filter(Boolean)
    .some((t) => t.toLowerCase() === needle);
}

export function toggleOperator(query: string, op: string): string {
  const tokens = query.split(/\s+/).filter(Boolean);
  const idx = tokens.findIndex((t) => t.toLowerCase() === op.toLowerCase());
  if (idx >= 0) tokens.splice(idx, 1);
  else tokens.push(op);
  return tokens.join(" ");
}

/** Which date preset is currently encoded in the query, or "any". */
export function activeDatePreset(query: string, now: Date = new Date()): string {
  for (const p of DATE_PRESETS) {
    if (p.days === null) continue;
    if (hasOperator(query, `after:${afterDateForDays(p.days, now)}`)) {
      return p.id;
    }
  }
  return "any";
}

/** Apply a date preset by rewriting any existing after: token (stale ones
 * included — a chip click is a statement about the whole date dimension). */
export function applyDatePreset(query: string, preset: DatePreset, now: Date = new Date()): string {
  const tokens = query.split(/\s+/).filter((t) => t && !t.toLowerCase().startsWith("after:"));
  if (preset.days !== null) tokens.push(`after:${afterDateForDays(preset.days, now)}`);
  return tokens.join(" ");
}
