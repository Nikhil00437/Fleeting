/**
 * #46 random old note, #47 this day last year, #297 weekly time capsule.
 *
 * One card, three draws. The capsule is week-stable server-side, so it only
 * needs fetching once per mount; "surprise me" re-rolls with a fresh seed.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Note } from "../types";

type Kind = "random" | "this_day" | "capsule";

const LABEL: Record<Kind, { tab: string; heading: (n: Note) => string }> = {
  random: { tab: "Surprise me", heading: (n) => `From ${fmtAge(n.created_at)}` },
  this_day: { tab: "This day", heading: (n) => `Captured on ${n.created_at.slice(0, 10)}` },
  capsule: { tab: "Time capsule", heading: (n) => `From ${fmtAge(n.created_at)}` },
};

function fmtAge(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 60) return `${days} days ago`;
  if (days < 730) return `${Math.round(days / 30)} months ago`;
  return `${(days / 365).toFixed(1)} years ago`;
}

export default function RecallCard({ onOpenNote }: { onOpenNote: (id: string) => void }) {
  const [kind, setKind] = useState<Kind>("capsule");
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [roll, setRoll] = useState(0);

  const load = useCallback(() => {
    api
      .recall(kind, roll)
      .then(setNotes)
      .catch(() => setNotes([]));
  }, [kind, roll]);

  useEffect(load, [load]);

  return (
    <section className="glass-studio rounded-2xl p-3.5" aria-label="Resurfaced notes">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="micro-label">From your past</span>
        <div className="flex items-center gap-0.5 rounded-lg border border-ink-800 bg-ink-900/80 p-0.5">
          {(Object.keys(LABEL) as Kind[]).map((k) => (
            <button
              key={k}
              onClick={() => {
                setKind(k);
                setNotes(null);
              }}
              aria-pressed={kind === k}
              className={`rounded-md px-2 py-0.5 font-mono text-[10.5px] ${
                kind === k ? "bg-ember-500/25 font-semibold text-ember-300" : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {LABEL[k].tab}
            </button>
          ))}
          <button
            onClick={() => setRoll((r) => r + 1)}
            title="Show another"
            aria-label="Show another resurfaced note"
            className="rounded-md px-1.5 py-0.5 font-mono text-[10.5px] text-ink-400 hover:text-ink-200"
          >
            ⟳
          </button>
        </div>
      </div>
      {notes === null ? (
        <div className="shimmer h-10 rounded-xl" />
      ) : notes.length === 0 ? (
        <p className="text-xs text-ink-400">Nothing that far back yet — keep capturing.</p>
      ) : (
        <ul className="space-y-1">
          {notes.map((n) => (
            <li key={n.id}>
              <button
                onClick={() => onOpenNote(n.id)}
                className="w-full rounded-lg px-2 py-1 text-left hover:bg-white/[0.04]"
              >
                <span className="block truncate text-xs text-ink-100">{n.title || "Untitled"}</span>
                <span className="block font-mono text-[10px] text-ink-400">{LABEL[kind].heading(n)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}