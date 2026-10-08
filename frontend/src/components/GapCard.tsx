/**
 * #337 "You were away 3h30m — what happened?"
 *
 * Only stretches worth remembering are offered (the backend filters short
 * ones), and answering writes a synthetic session so the day stops having a
 * hole in it — reports and streak maths both read from the same rows.
 */

import { useState } from "react";
import { api } from "../api";
import type { ActivityGap } from "../types";

type OnToast = (msg: string, kind?: "ok" | "err") => void;

function human(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m}m`;
  return m ? `${h}h${String(m).padStart(2, "0")}m` : `${h}h`;
}

export default function GapCard({
  gaps,
  onFilled,
  onToast,
}: {
  gaps: ActivityGap[];
  onFilled: () => void;
  onToast: OnToast;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [minutes, setMinutes] = useState(30);
  const [busy, setBusy] = useState(false);

  if (gaps.length === 0) return null;
  const total = gaps.reduce((n, g) => n + g.minutes, 0);
  const target = gaps[0];

  const submit = () => {
    if (!note.trim()) {
      onToast("Say what you were doing first", "err");
      return;
    }
    setBusy(true);
    api
      .fillGap(target.start, minutes, note.trim())
      .then(() => {
        onToast("Gap filled in");
        setNote("");
        setOpen(false);
        onFilled();
      })
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => setBusy(false));
  };

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Untracked time">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-xs text-ink-200">
          <strong className="font-semibold text-ink-100">
            {gaps.length === 1 ? `Away ${human(total)}` : `${gaps.length} gaps, ${human(total)} total`}
          </strong>{" "}
          — the record has holes. Fill one in?
        </p>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="rounded-lg border border-ember-500/30 bg-ember-500/10 px-2.5 py-1 text-[11px] text-ember-300 hover:bg-ember-500/20"
        >
          {open ? "Close" : "Fill a gap"}
        </button>
      </div>

      {open && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-white/[0.06] pt-2.5">
          <span className="font-mono text-[10.5px] text-ink-400">
            {target.start.slice(11, 16)}–{target.end.slice(11, 16)}
          </span>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-label="What were you doing"
            placeholder="Offsite interview, dentist, reading…"
            className="min-w-40 flex-1 rounded-lg border border-ink-800 bg-ink-900 px-2 py-1 text-xs text-ink-100 placeholder-ink-500"
          />
          <input
            type="number"
            min={1}
            max={1440}
            value={minutes}
            onChange={(e) => setMinutes(Math.max(1, Number(e.target.value) || 1))}
            aria-label="Gap length in minutes"
            className="h-7 w-20 rounded-lg border border-ink-800 bg-ink-900 px-1 text-center font-mono text-[11px] text-ink-200"
          />
          <button
            disabled={busy}
            onClick={submit}
            className="rounded-lg border border-ember-500/30 bg-ember-500/10 px-3 py-1 text-[11px] text-ember-300 disabled:opacity-50"
          >
            Record it
          </button>
        </div>
      )}
    </section>
  );
}