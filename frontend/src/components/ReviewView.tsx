import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { relTime } from "../time";
import type { TaskItem } from "../types";

/**
 * #38 weekly review — the carry-over-or-drop screen. Piles come from
 * /api/tasks/review; the decisions reuse the ordinary task PATCH so the
 * review never grows its own write path.
 */
function Pile({
  title,
  tasks,
  hint,
  render,
  empty,
}: {
  title: string;
  tasks: TaskItem[];
  hint?: string;
  render: (t: TaskItem) => React.ReactNode;
  empty: string;
}) {
  return (
    <section className="glass-studio rounded-2xl p-4">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="micro-label">{title}</span>
        <span className="font-mono text-[10px] text-ink-500">{tasks.length}</span>
      </div>
      {hint && <p className="mb-2 text-[11px] text-ink-500">{hint}</p>}
      {tasks.length === 0 ? (
        <p className="text-[11px] text-ink-600">{empty}</p>
      ) : (
        <ul className="space-y-1.5">{tasks.map((t) => <li key={t.id}>{render(t)}</li>)}</ul>
      )}
    </section>
  );
}

export default function ReviewView({ onToast }: { onToast?: (m: string, k?: "ok" | "err") => void }) {
  const [review, setReview] = useState<Awaited<ReturnType<typeof api.weeklyReview>> | null>(null);

  const load = useCallback(() => {
    api.weeklyReview().then(setReview).catch((e) => onToast?.(String(e), "err"));
  }, [onToast]);

  useEffect(load, [load]);

  const act = useCallback(
    async (fn: () => Promise<unknown>, message: string) => {
      try {
        await fn();
        onToast?.(message);
        load();
      } catch (e) {
        onToast?.(e instanceof Error ? e.message : String(e), "err");
      }
    },
    [load, onToast]
  );

  if (!review) return <div className="shimmer m-5 h-64 rounded-2xl" />;

  // UTC arithmetic, not local Date: `new Date("2026-10-05")` is UTC midnight,
  // so toISOString() can slip a day in a negative-offset zone.
  const carryDate = new Date(
    Date.parse(`${review.week_start}T00:00:00Z`) + 7 * 24 * 60 * 60 * 1000
  )
    .toISOString()
    .slice(0, 10);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-3 p-5">
      <header className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold text-ink-100">Weekly review</h1>
        <span className="font-mono text-[10px] text-ink-500">
          week of {review.week_start} · {Math.round(review.stats.completion_rate * 100)}% closed
        </span>
      </header>

      <Pile
        title="Slipped — carry or drop"
        hint="Due before this week and still open. Carry moves it to next Monday; drop shelves it."
        tasks={review.carry_over}
        empty="nothing slipped"
        render={(t) => (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-[13px] text-ink-100">{t.text}</p>
              <p className="font-mono text-[10px] text-ink-500">due {t.due_date}</p>
            </div>
            <div className="flex shrink-0 gap-1.5">
              <button
                onClick={() => void act(() => api.updateTask(t.id, { due_date: carryDate }), `carried to ${carryDate}`)}
                className="rounded-lg border border-ember-400/40 bg-ember-500/15 px-2 py-1 text-[11px] text-ember-300"
              >
                Carry
              </button>
              <button
                onClick={() => void act(() => api.updateTask(t.id, { list: "someday" }), "dropped to someday")}
                className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 text-[11px] text-ink-300"
              >
                Drop
              </button>
            </div>
          </div>
        )}
      />

      <Pile
        title="Due this week"
        tasks={review.this_week}
        empty="nothing due this week"
        render={(t) => (
          <div className="flex items-center justify-between gap-3">
            <p className="min-w-0 truncate text-[13px] text-ink-100">{t.text}</p>
            <span className="shrink-0 font-mono text-[10px] text-ink-500">{t.due_date}</span>
          </div>
        )}
      />

      <Pile
        title="Closed this week"
        tasks={review.completed}
        empty="nothing closed yet"
        render={(t) => (
          <div className="flex items-center justify-between gap-3">
            <p className="min-w-0 truncate text-[13px] text-ink-400 line-through">{t.text}</p>
            <span className="shrink-0 font-mono text-[10px] text-ink-500">
              {t.completed_at ? relTime(t.completed_at) : ""}
            </span>
          </div>
        )}
      />
    </div>
  );
}