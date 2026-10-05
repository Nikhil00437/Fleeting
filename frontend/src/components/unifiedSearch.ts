/** Presentation for activity-aware search.
 *
 * The backend returns every bucket, including empty ones, so the UI can render
 * "no commits matched" instead of silently showing nothing.
 */

import { fmtSecs } from "../apps";
import type { UnifiedResult } from "../types";

type SessionHit = UnifiedResult["sessions"][number];

/** What the bucket tabs need: lengths and counts, not whole rows. */
export type BucketCounts = {
  notes: unknown[];
  sessions: unknown[];
  commits: unknown[];
  counts?: { notes: number; sessions: number; commits: number };
  total?: number;
};

export interface BucketRow {
  key: "notes" | "sessions" | "commits";
  label: string;
  count: number;
}

export function emptyUnified(): BucketCounts {
  return {
    notes: [],
    sessions: [],
    commits: [],
    counts: { notes: 0, sessions: 0, commits: 0 },
    total: 0,
  };
}

export function bucketCounts(u: BucketCounts | null | undefined): BucketRow[] {
  const fallback = (arr: unknown[] | undefined) => (Array.isArray(arr) ? arr.length : 0);
  const c = u?.counts;
  return [
    { key: "notes", label: "Notes", count: c ? c.notes : fallback(u?.notes) },
    { key: "sessions", label: "Windows", count: c ? c.sessions : fallback(u?.sessions) },
    { key: "commits", label: "Commits", count: c ? c.commits : fallback(u?.commits) },
  ];
}

/** "code · 1h 30m — fleeting — routers/notes.py" */
export function sessionLabel(s: Partial<SessionHit> | null | undefined): string {
  if (!s) return "Window session";
  const app = (s.app_class || "").trim();
  const title = (s.title || "").trim();
  const dur = typeof s.seconds === "number" && s.seconds > 0 ? fmtSecs(s.seconds) : "";
  const head = app || title || "Window session";
  const tail = app && title ? ` — ${title}` : "";
  return [head, dur, tail].filter(Boolean).join(" ");
}
