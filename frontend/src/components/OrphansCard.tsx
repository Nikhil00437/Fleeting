import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

type Orphans = {
  single_use_tags: string[];
  untagged_notes: { id: string; title: string }[];
  unlinked_tasks: { id: string; text: string }[];
};

/**
 * #422 orphan detection — the housekeeping panel. Names the work nothing
 * points at: tags only one note uses, finished notes with no tags, and
 * tasks hanging off the synthetic Inbox note instead of a real capture.
 */
export default function OrphansCard({ onToast, refreshKey }: { onToast?: (m: string, k?: "ok" | "err") => void; refreshKey?: number }) {
  const [data, setData] = useState<Orphans | null>(null);

  const load = useCallback(() => {
    api.orphans().then(setData).catch((e) => onToast?.(String(e), "err"));
  }, [onToast]);

  useEffect(load, [load, refreshKey]);

  if (!data) return <div className="shimmer h-32 rounded-2xl" />;

  const total =
    data.single_use_tags.length + data.untagged_notes.length + data.unlinked_tasks.length;

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Housekeeping">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="micro-label">Unfiled work</span>
        <span className="font-mono text-[10px] text-ink-500">{total} orphan{total === 1 ? "" : "s"}</span>
      </div>
      {total === 0 ? (
        <p className="text-[11px] text-ink-500">Everything is filed. Nothing points at nothing.</p>
      ) : (
        <div className="grid gap-2 sm:grid-cols-3">
          <div>
            <p className="font-mono text-[10px] text-ink-500">single-use tags</p>
            <p className="text-lg font-semibold text-ink-100">{data.single_use_tags.length}</p>
            <p className="truncate text-[11px] text-ink-400">{data.single_use_tags.slice(0, 6).join(", ") || "—"}</p>
          </div>
          <div>
            <p className="font-mono text-[10px] text-ink-500">untagged notes</p>
            <p className="text-lg font-semibold text-ink-100">{data.untagged_notes.length}</p>
            <p className="truncate text-[11px] text-ink-400">
              {data.untagged_notes.slice(0, 3).map((n) => n.title).join(", ") || "—"}
            </p>
          </div>
          <div>
            <p className="font-mono text-[10px] text-ink-500">unlinked tasks</p>
            <p className="text-lg font-semibold text-ink-100">{data.unlinked_tasks.length}</p>
            <p className="truncate text-[11px] text-ink-400">
              {data.unlinked_tasks.slice(0, 3).map((t) => t.text).join(", ") || "—"}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}