/**
 * #65 private mode, the in-app half of the tray's "Private for…".
 *
 * A paused tracker is otherwise a mystery: this says *why* and how long is
 * left, and offers the one-click undo.
 */

import { useEffect, useState } from "react";
import { api } from "../api";

type OnToast = (msg: string, kind?: "ok" | "err") => void;

function untilText(until: string): string {
  const mins = Math.max(0, Math.round((new Date(until).getTime() - Date.now()) / 60000));
  if (mins < 1) return "ending…";
  if (mins < 60) return `${mins} min left`;
  const h = Math.floor(mins / 60);
  return `${h}h ${mins % 60}m left`;
}

export default function PrivateBadge({ onToast }: { onToast: OnToast }) {
  const [until, setUntil] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api
      .privateState()
      .then((r) => setUntil(r.active ? r.until : null))
      .catch(() => setUntil(null));
  };
  useEffect(load, []);

  if (!until) return null;

  const start = (minutes: number) => {
    setBusy(true);
    api
      .startPrivate(minutes)
      .then(() => onToast(`Tracking paused for ${minutes} minutes`))
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => {
        setBusy(false);
        load();
      });
  };

  const stop = () => {
    api
      .stopPrivate()
      .then(() => onToast("Tracking resumed"))
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(load);
  };

  return (
    <div
      className="flex items-center gap-2 rounded-xl border border-ember-500/30 bg-ember-500/10 px-2.5 py-1"
      role="status"
      aria-label="Private mode is on"
    >
      <span aria-hidden>🔒</span>
      <span className="text-[11px] font-medium text-ember-200">Private</span>
      <span className="font-mono text-[10.5px] text-ember-300/80">{untilText(until)}</span>
      <button
        disabled={busy}
        onClick={() => start(30)}
        className="rounded-lg border border-ember-500/30 px-1.5 py-0.5 text-[10.5px] text-ember-200 disabled:opacity-50"
      >
        +30m
      </button>
      <button
        disabled={busy}
        onClick={stop}
        className="rounded-lg border border-emerald-500/30 px-1.5 py-0.5 text-[10.5px] text-emerald-300 disabled:opacity-50"
      >
        Resume
      </button>
    </div>
  );
}