/**
 * #30 Today view: what's due, what you finished, and what to do now (#33).
 *
 * The ranking lives in the backend (services/whatnow.py) — this component
 * only renders buckets and toggles tasks. Day load (#32) is estimated work
 * vs the configured daily capacity.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { TaskItem, TodayData } from "../types";
import { CheckIcon, ClockIcon } from "../components/Icons";
import { cyclePriority, formatDueDate } from "./TasksView";

type OnToast = (msg: string, kind?: "ok" | "err") => void;

const PRIORITY_CLASS: Record<string, string> = {
  P1: "bg-red-500/20 text-red-400",
  P2: "bg-amber-500/20 text-amber-400",
  P3: "bg-slate-500/20 text-slate-300",
};

function PriorityBadge({ task }: { task: TaskItem }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        void api
          .updateTask(task.id, { priority: cyclePriority(task.priority) })
          .catch(() => {});
      }}
      title="Cycle priority"
      aria-label={`Priority ${task.priority} — click to cycle`}
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold ${PRIORITY_CLASS[task.priority] ?? PRIORITY_CLASS.P3}`}
    >
      {task.priority}
    </button>
  );
}

function TaskRow({
  task,
  onToggle,
  onOpenNote,
}: {
  task: TaskItem;
  onToggle: (t: TaskItem) => void;
  onOpenNote?: (id: string) => void;
}) {
  const due = formatDueDate(task.due_date);
  return (
    <li className="flex items-center gap-2.5 rounded-xl border border-ink-800/60 bg-ink-950/50 px-3 py-2">
      <button
        onClick={() => onToggle(task)}
        aria-label={`Mark “${task.text}” ${task.done ? "open" : "done"}`}
        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-ink-600 text-transparent transition-colors hover:border-ember-400 hover:text-ember-400"
      >
        <CheckIcon className="h-2.5 w-2.5" />
      </button>
      <span
        className={`flex-1 truncate text-xs ${task.done ? "text-ink-500 line-through" : "text-ink-200"}`}
      >
        {task.text}
      </span>
      {task.estimate_min ? (
        <span className="font-mono text-[10px] text-ink-500" title="Estimated minutes">
          {task.estimate_min}m
        </span>
      ) : null}
      {task.recurrence && (
        <span
          className="text-[10px] text-ink-500"
          title={`Repeats (${task.recurrence.toLowerCase()})`}
        >
          ↻
        </span>
      )}
      {task.context && (
        <span className="rounded bg-iris-500/15 px-1.5 py-0.5 font-mono text-[10px] text-iris-300">
          @{task.context}
        </span>
      )}
      {task.repo && (
        <span className="rounded bg-ink-800/80 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
          +{task.repo}
        </span>
      )}
      {task.due_date && (
        <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${due.className}`}>
          {due.label}
        </span>
      )}
      {onOpenNote && task.note_id && (
        <button
          onClick={() => onOpenNote(task.note_id)}
          className="font-mono text-[10px] text-ink-500 hover:text-ember-400"
          title={task.note_title || "Open source note"}
        >
          note ↗
        </button>
      )}
    </li>
  );
}

function LoadBar({ load }: { load: TodayData["load"] }) {
  const cap = Math.max(1, load.capacity_min);
  const estPct = Math.min(100, Math.round((load.estimated_min / cap) * 100));
  const over = load.estimated_min > cap;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="micro-label">Day load</span>
        <span className={`font-mono text-[10px] ${over ? "text-red-400" : "text-ink-400"}`}>
          {Math.round(load.estimated_min / 60 * 10) / 10}h planned /{" "}
          {Math.round(load.capacity_min / 60 * 10) / 10}h capacity
          {load.spent_min > 0 ? ` · ${load.spent_min}m done` : ""}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-ink-900"
        role="meter"
        aria-valuenow={load.estimated_min}
        aria-valuemin={0}
        aria-valuemax={load.capacity_min}
        aria-label="Planned time versus daily capacity"
      >
        <div
          className={`h-full rounded-full transition-all ${over ? "bg-red-500/70" : "bg-emerald-500/60"}`}
          style={{ width: `${estPct}%` }}
        />
      </div>
      {over && (
        <p className="mt-1 text-[10px] text-red-400/90">
          Over capacity — move something to tomorrow or to someday.
        </p>
      )}
    </div>
  );
}

export default function TodayView({
  refreshKey,
  onToast,
  onOpenNote,
  onTasksChanged,
  initialData = null,
}: {
  refreshKey: number;
  onToast: OnToast;
  onOpenNote?: (id: string) => void;
  onTasksChanged?: () => void;
  /** Pre-fetched payload (tests, or a future prefetch); avoids the shimmer. */
  initialData?: TodayData | null;
}) {
  const [data, setData] = useState<TodayData | null>(initialData);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .today()
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(load, [load, refreshKey]);

  const toggle = (t: TaskItem) => {
    api
      .toggleTask(t.id)
      .then(() => {
        load();
        onTasksChanged?.();
      })
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"));
  };

  if (error) {
    return <div className="p-5 text-xs text-red-400">{error}</div>;
  }
  if (!data) {
    return (
      <div className="space-y-2.5 p-5">
        <div className="shimmer h-28 rounded-2xl" />
        <div className="shimmer h-16 rounded-2xl" />
      </div>
    );
  }

  const next = data.next_action;
  const openCount = data.overdue.length + data.due_today.length;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-5">
      <header className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold text-ink-100">Today</h1>
        <span className="font-mono text-[10px] text-ink-500">
          {data.day} · {openCount} open · {data.completed_today.length} done
        </span>
      </header>

      {next ? (
        <section className="glass-studio rounded-2xl p-4" aria-label="Next action">
          <span className="micro-label flex items-center gap-1.5">
            <ClockIcon className="h-3 w-3 text-ember-400" />
            Do this now
          </span>
          <div className="mt-2 flex items-start gap-3">
            <button
              onClick={() => toggle(next)}
              aria-label={`Mark “${next.text}” done`}
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-ink-500 text-transparent transition-colors hover:border-emerald-400 hover:text-emerald-400"
            >
              <CheckIcon className="h-3 w-3" />
            </button>
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink-100">{next.text}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <PriorityBadge task={next} />
                {next.due_date && (
                  <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${formatDueDate(next.due_date).className}`}>
                    {formatDueDate(next.due_date).label}
                  </span>
                )}
                {next.estimate_min ? (
                  <span className="font-mono text-[10px] text-ink-500">~{next.estimate_min}m</span>
                ) : null}
                {next.context && (
                  <span className="rounded bg-iris-500/15 px-1.5 py-0.5 font-mono text-[10px] text-iris-300">
                    @{next.context}
                  </span>
                )}
                {next.repo && (
                  <span className="rounded bg-ink-800/80 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
                    +{next.repo}
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>
      ) : (
        <section className="glass-studio rounded-2xl p-4 text-xs text-ink-400" aria-label="Next action">
          Nothing queued — capture a thought or pull something from someday.
        </section>
      )}

      <section className="glass-studio rounded-2xl p-4">
        <LoadBar load={data.load} />
      </section>

      {data.overdue.length > 0 && (
        <section aria-label="Overdue">
          <span className="micro-label mb-1.5 block text-red-400/90">Overdue</span>
          <ul className="space-y-1.5">
            {data.overdue.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={toggle} onOpenNote={onOpenNote} />
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Due today">
        <span className="micro-label mb-1.5 block">Due today</span>
        {data.due_today.length === 0 ? (
          <p className="text-xs text-ink-500">Nothing due today.</p>
        ) : (
          <ul className="space-y-1.5">
            {data.due_today.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={toggle} onOpenNote={onOpenNote} />
            ))}
          </ul>
        )}
      </section>

      {data.up_next.length > 0 && (
        <section aria-label="Up next">
          <span className="micro-label mb-1.5 block">Up next</span>
          <ul className="space-y-1.5">
            {data.up_next.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={toggle} onOpenNote={onOpenNote} />
            ))}
          </ul>
        </section>
      )}

      {data.waiting.length > 0 && (
        <section aria-label="Waiting for">
          <span className="micro-label mb-1.5 block">Waiting for</span>
          <ul className="space-y-1.5">
            {data.waiting.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={toggle} onOpenNote={onOpenNote} />
            ))}
          </ul>
        </section>
      )}

      {data.completed_today.length > 0 && (
        <section aria-label="Completed today">
          <span className="micro-label mb-1.5 block text-emerald-400/90">
            Done today ({data.completed_today.length})
          </span>
          <ul className="space-y-1.5">
            {data.completed_today.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={toggle} onOpenNote={onOpenNote} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
