/**
 * #341 rewind: scrub or replay the day.
 *
 * Everything here reads the sessions the timeline already has — the scrubber
 * is a lens over the day, not a second source of truth, so what you see while
 * rewinding is exactly what the ribbon and the totals would say at that hour.
 */

import { useEffect, useMemo, useState } from "react";
import type { ActivitySession } from "../types";

/** Playback speed: 10 minutes of the day per tick. */
const TICK_MINUTES = 10;
const TICK_MS = 250;
const MAX_MINUTES = 24 * 60;

function minutesInto(iso: string): number {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 0 : d.getHours() * 60 + d.getMinutes();
}

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${String(m).padStart(2, "0")}m` : `${h}h`;
}

function hhmm(minutes: number): string {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

export default function RewindBar({ sessions }: { sessions: ActivitySession[] }) {
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    const t = window.setInterval(() => {
      setCursor((c) => {
        const next = (c ?? 0) + TICK_MINUTES;
        if (next >= MAX_MINUTES) {
          setPlaying(false);
          return MAX_MINUTES;
        }
        return next;
      });
    }, TICK_MS);
    return () => window.clearInterval(t);
  }, [playing]);

  // Sessions that have already happened at the cursor; `null` = the whole day.
  const soFar = useMemo(
    () =>
      cursor === null
        ? sessions
        : sessions.filter((s) => minutesInto(s.first_seen) <= cursor),
    [sessions, cursor],
  );
  const total = useMemo(
    () => soFar.reduce((n, s) => n + (s.seconds || 0), 0),
    [soFar],
  );

  if (sessions.length === 0) return null;

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Rewind the day">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="micro-label">Rewind</p>
        <p className="text-[11px] text-ink-400">
          {cursor === null ? (
            <>whole day · <strong className="font-mono text-ink-100">{fmtSecs(total)}</strong></>
          ) : (
            <>
              by <strong className="font-mono text-ember-300">{hhmm(cursor)}</strong> ·{" "}
              <strong className="font-mono text-ink-100">{fmtSecs(total)}</strong> across{" "}
              {soFar.length} sessions
            </>
          )}
        </p>
      </div>

      <div className="flex items-center gap-2.5">
        <button
          onClick={() => {
            if (cursor === null) setCursor(0);
            setPlaying((p) => !p);
          }}
          aria-label={playing ? "Pause the replay" : "Replay the day"}
          className="shrink-0 rounded-lg border border-ember-500/30 bg-ember-500/10 px-2.5 py-1 text-[11px] text-ember-300"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={MAX_MINUTES}
          step={5}
          value={cursor ?? MAX_MINUTES}
          onChange={(e) => {
            setPlaying(false);
            setCursor(Number(e.target.value));
          }}
          aria-label="Rewind position"
          className="h-1.5 flex-1 accent-ember-500"
        />
        {cursor !== null && (
          <button
            onClick={() => {
              setPlaying(false);
              setCursor(null);
            }}
            className="shrink-0 rounded-lg border border-ink-800 px-2 py-1 text-[11px] text-ink-300"
          >
            Whole day
          </button>
        )}
      </div>

      {cursor !== null && soFar.length > 0 && (
        <ul className="mt-2.5 max-h-32 space-y-0.5 overflow-y-auto">
          {soFar
            .slice()
            .reverse()
            .map((s) => (
              <li key={s.id} className="flex items-center gap-2 text-[11px] text-ink-300">
                <span className="font-mono text-[10px] text-ink-500">{hhmm(minutesInto(s.first_seen))}</span>
                <span className="truncate">{s.title || s.app_class}</span>
                <span className="ml-auto shrink-0 font-mono text-[10px] text-ink-500">
                  {fmtSecs(s.seconds || 0)}
                </span>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}