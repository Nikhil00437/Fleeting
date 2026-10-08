/**
 * #54 editing a session the collector guessed wrong: relabel, split, delete.
 *
 * The split point is prefilled with the session's midpoint because "cut it
 * roughly in half" is the common case; the exact minute is one edit away when
 * it isn't. Merging lives on the feed itself (checkboxes) — it needs a
 * selection, so it is not a per-row action.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type { ActivitySession } from "../types";

type OnToast = (msg: string, kind?: "ok" | "err") => void;

/** Local wall-clock `YYYY-MM-DDTHH:MM`, the shape `datetime-local` wants.

    The stored session times are local naive ISO, so going through UTC here
    would show — and send — a split point up to a day off.
*/
function localStamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function midpoint(session: ActivitySession): string {
  const start = new Date(session.first_seen).getTime();
  const end = new Date(session.last_seen).getTime();
  const mid = Number.isFinite(start) && Number.isFinite(end) && end > start ? (start + end) / 2 : start;
  return localStamp(mid);
}

export default function SessionEditor({
  session,
  onDone,
  onChanged,
  onToast,
}: {
  session: ActivitySession;
  /** Called after any successful edit, including closing the panel. */
  onDone: () => void;
  onChanged: () => void;
  onToast: OnToast;
}) {
  const [title, setTitle] = useState(session.title);
  const [note, setNote] = useState(session.note ?? "");
  const [splitAt, setSplitAt] = useState(() => midpoint(session));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTitle(session.title);
    setNote(session.note ?? "");
    setSplitAt(midpoint(session));
  }, [session.id, session.title, session.note]);

  const run = (action: () => Promise<unknown>, ok: string, close = true) => {
    setBusy(true);
    action()
      .then(() => {
        onToast(ok);
        onChanged();
        if (close) onDone();
      })
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => setBusy(false));
  };

  return (
    <div
      className="my-1 flex flex-wrap items-center gap-2 rounded-xl border border-white/[0.07] bg-ink-950/70 px-3 py-2 text-xs"
      role="group"
      aria-label="Session editor"
    >
      <span className="font-mono text-[10.5px] text-ink-500">
        {session.first_seen.slice(11, 16)}–{session.last_seen.slice(11, 16)}
      </span>
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Session label"
        placeholder="Name this session"
        className="min-w-40 flex-1 rounded-lg border border-ink-800 bg-ink-900 px-2 py-1 text-xs text-ink-100 placeholder-ink-500"
      />
      <button
        disabled={busy || title.trim() === session.title}
        onClick={() => run(() => api.relabelSession(session.id, title), "Session renamed", false)}
        className="rounded-lg border border-ember-500/30 bg-ember-500/10 px-2 py-1 text-[11px] text-ember-300 disabled:opacity-50"
      >
        Save name
      </button>

      {/* #334 what this stretch was actually for; daily reports quote it */}
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        aria-label="Session note"
        placeholder="What were you doing?"
        className="min-w-40 flex-1 rounded-lg border border-ink-800 bg-ink-900 px-2 py-1 text-xs text-ink-100 placeholder-ink-500"
      />
      <button
        disabled={busy || note === (session.note ?? "")}
        onClick={() => run(() => api.annotateSession(session.id, note), "Note saved", false)}
        className="rounded-lg border border-iris-500/30 bg-iris-500/10 px-2 py-1 text-[11px] text-iris-300 disabled:opacity-50"
      >
        Save note
      </button>

      <span className="ml-2 font-mono text-[10.5px] text-ink-500">split at</span>
      <input
        type="datetime-local"
        value={splitAt}
        onChange={(e) => setSplitAt(e.target.value)}
        aria-label="Split at"
        className="rounded-lg border border-ink-800 bg-ink-900 px-2 py-1 font-mono text-[11px] text-ink-100"
      />
      <button
        disabled={busy}
        onClick={() =>
          run(
            () => api.splitSession(session.id, splitAt.length === 16 ? `${splitAt}:00` : splitAt),
            "Session split",
          )
        }
        className="rounded-lg border border-ink-700 px-2 py-1 text-[11px] text-ink-300 disabled:opacity-50"
      >
        Split
      </button>

      <button
        disabled={busy}
        onClick={() => run(() => api.deleteSession(session.id), "Session deleted")}
        className="ml-auto rounded-lg border border-red-500/30 px-2 py-1 text-[11px] text-red-300 disabled:opacity-50"
      >
        Delete
      </button>
    </div>
  );
}