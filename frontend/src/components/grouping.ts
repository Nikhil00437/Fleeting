/**
 * #316: group search results by day, tag or project.
 *
 * Pure so it can be tested without a DOM — same rule as serverEvents.ts.
 * A note can belong to several tag groups; it is listed under each, which is
 * what "group by tag" means everywhere else. Projects come from
 * `source.repo` (the markdown repo a capture came from).
 */

import type { Note } from "../types";

export type GroupBy = "none" | "day" | "tag" | "project";

export interface Group {
  key: string;
  label: string;
  items: Note[];
}

const UNTAGGED = "untagged";
const NO_PROJECT = "no project";

/** Today / Yesterday / a weekday / a date — the order buckets arrive in. */
export function dayLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "undated";
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const age = Math.floor((day - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000);
  if (age === 0) return "Today";
  if (age === 1) return "Yesterday";
  if (age > 1 && age < 7) return d.toLocaleDateString(undefined, { weekday: "long" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function repoOf(note: Note): string | null {
  const repo = note.source?.repo;
  return typeof repo === "string" && repo.trim() ? repo.trim() : null;
}

export function groupNotes(notes: Note[], by: GroupBy, now = new Date()): Group[] {
  if (by === "none") return notes.length ? [{ key: "all", label: "", items: notes }] : [];

  const buckets = new Map<string, { label: string; items: Note[] }>();
  const add = (key: string, label: string, note: Note) => {
    const b = buckets.get(key) ?? { label, items: [] };
    b.items.push(note);
    buckets.set(key, b);
  };

  for (const n of notes) {
    if (by === "day") add(n.created_at.slice(0, 10), dayLabel(n.created_at, now), n);
    else if (by === "tag") {
      const tags = n.tags?.length ? n.tags : [UNTAGGED];
      for (const t of tags) add(t, t === UNTAGGED ? UNTAGGED : `#${t}`, n);
    } else {
      const repo = repoOf(n) ?? NO_PROJECT;
      add(repo, repo, n);
    }
  }

  return [...buckets.entries()]
    .map(([key, b]) => ({ key, label: b.label, items: b.items }))
    .sort((a, b) => (by === "day" ? b.key.localeCompare(a.key) : b.items.length - a.items.length));
}