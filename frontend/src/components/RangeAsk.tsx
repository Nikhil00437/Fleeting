/**
 * #63 drag a range on the ribbon, ask what you were doing.
 *
 * Dragging on the ribbon is the natural gesture: the user already knows
 * *where* on the day they are pointing at, so the only text input needed is
 * the question (and there is a sensible default).
 */

import { useRef, useState } from "react";
import { api } from "../api";
import type { WindowAnswer } from "../types";

type OnToast = (msg: string, kind?: "ok" | "err") => void;

function stamp(day: string, fraction: number): string {
  const mins = Math.max(0, Math.min(24 * 60, Math.round(fraction * 24 * 60)));
  const hh = String(Math.floor(mins / 60)).padStart(2, "0");
  const mm = String(mins % 60).padStart(2, "0");
  return `${day}T${hh}:${mm}:00`;
}

function hhmm(iso: string): string {
  return iso.slice(11, 16);
}

export default function RangeAsk({
  day,
  onOpenNote,
  onToast,
}: {
  day: string;
  onOpenNote?: (id: string) => void;
  onToast: OnToast;
}) {
  const [range, setRange] = useState<[number, number] | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<WindowAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const dragStart = useRef<number | null>(null);

  const fraction = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  };

  const onMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    dragStart.current = fraction(e);
  };

  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (dragStart.current === null) return;
    const f = fraction(e);
    setRange([Math.min(dragStart.current, f), Math.max(dragStart.current, f)]);
  };

  const onMouseUp = () => {
    dragStart.current = null;
  };

  const ask = () => {
    if (!range) return;
    setBusy(true);
    api
      .askWindow(day, stamp(day, range[0]), stamp(day, range[1]), question)
      .then(setAnswer)
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => setBusy(false));
  };

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Ask about a stretch">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <p className="micro-label">Ask about a stretch — drag on the bar</p>
        {range && (
          <span className="font-mono text-[10.5px] text-ink-400">
            {hhmm(stamp(day, range[0]))}–{hhmm(stamp(day, range[1]))}
          </span>
        )}
      </div>

      {/* A transparent strip over the ribbon's row; the ribbon itself renders
          underneath, so the drag reads as marking up the day, not a widget. */}
      <div
        className="relative h-4 cursor-crosshair"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        <div className="absolute inset-x-0 top-1.5 h-px bg-white/[0.06]" />
        {range && (
          <div
            className="absolute top-0 h-4 rounded bg-ember-500/25 ring-1 ring-ember-400/50"
            style={{
              left: `${range[0] * 100}%`,
              width: `${Math.max(0.5, (range[1] - range[0]) * 100)}%`,
            }}
          />
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What was I doing here?"
          aria-label="Question about the selected stretch"
          className="min-w-40 flex-1 rounded-lg border border-ink-800 bg-ink-950 px-2 py-1 text-xs text-ink-100 placeholder-ink-500"
        />
        <button
          disabled={!range || busy}
          onClick={ask}
          className="rounded-lg border border-ember-500/30 bg-ember-500/10 px-3 py-1 text-[11px] text-ember-300 disabled:opacity-40"
        >
          {busy ? "Asking…" : "Ask"}
        </button>
      </div>

      {answer && (
        <div className="mt-2.5 rounded-xl border border-white/[0.06] bg-ink-950/60 p-3">
          <p className="text-xs leading-relaxed whitespace-pre-wrap text-ink-200">{answer.answer}</p>
          {answer.sessions.length > 0 && (
            <ul className="mt-2 space-y-1">
              {answer.sessions.map((s) => (
                <li key={s.id}>
                  <button
                    onClick={() => onOpenNote?.(String(s.id))}
                    className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-white/[0.04]"
                  >
                    <span className="font-mono text-[10px] text-ink-500">{hhmm(s.first_seen)}</span>
                    <span className="truncate text-[11px] text-ink-300">
                      {s.app_class} · {s.title || "(untitled)"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}