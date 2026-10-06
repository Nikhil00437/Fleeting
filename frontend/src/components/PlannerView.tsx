import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { TaskItem, WeekPlan } from "../types";

/**
 * #279 time blocking: drag a task onto a day to give it that due date.
 * The week's packing comes from /api/tasks/plan (#284) and the bar under each
 * column is the capacity gauge (#442) — planned minutes against available
 * minutes — so one payload answers "when" and "is it too much".
 */
function fmtMin(min: number): string {
  if (min <= 0) return "0m";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h && m ? `${h}h ${m}m` : h ? `${h}h` : `${m}m`;
}

const DAY_LABEL = new Intl.DateTimeFormat("en", { weekday: "short", timeZone: "UTC" });

export default function PlannerView({
  onToast,
  refreshKey,
  onTasksChanged,
}: {
  onToast?: (m: string, k?: "ok" | "err") => void;
  refreshKey?: number;
  onTasksChanged?: () => void;
}) {
  const [plan, setPlan] = useState<WeekPlan | null>(null);
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropDay, setDropDay] = useState<string | null>(null);

  const load = useCallback(() => {
    api.weekPlan().then(setPlan).catch((e) => onToast?.(String(e), "err"));
    api.tasks({ list: "inbox", status: "open" }).then(setTasks).catch(() => {});
  }, [onToast]);

  useEffect(load, [load, refreshKey]);

  const byId = useCallback(
    (id: string) => tasks.find((t) => t.id === id),
    [tasks]
  );

  async function block(taskId: string, day: string) {
    try {
      await api.updateTask(taskId, { due_date: day });
      onToast?.(`blocked for ${day}`);
      onTasksChanged?.();
      load();
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : String(e), "err");
    }
  }

  if (!plan) return <div className="shimmer m-5 h-64 rounded-2xl" />;

  const planned = plan.totals.planned_min;
  const capacity = plan.totals.capacity_min || 1;

  return (
    <div className="mx-auto w-full max-w-5xl space-y-3 p-5">
      <header className="flex items-baseline justify-between">
        <h1 className="text-lg font-semibold text-ink-100">Week of {plan.week_start}</h1>
        <span className="font-mono text-[10px] text-ink-500">
          {fmtMin(planned)} planned of {fmtMin(plan.totals.capacity_min)} · {Math.round(plan.totals.utilization * 100)}%
        </span>
      </header>

      {/* #442 weekly capacity gauge */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-900">
        <div
          className={`h-full ${plan.totals.over_capacity ? "bg-red-400" : "bg-ember-400"}`}
          style={{ width: `${Math.min(100, Math.round((planned / capacity) * 100))}%` }}
        />
      </div>

      {/* #279 the week grid: drag a tray task onto a day */}
      <div className="grid grid-cols-7 gap-2">
        {plan.days.map((d) => {
          const label = DAY_LABEL.format(new Date(`${d.day}T00:00:00Z`));
          return (
            <div
              key={d.day}
              onDragOver={(e) => {
                e.preventDefault();
                setDropDay(d.day);
              }}
              onDragLeave={() => setDropDay((cur) => (cur === d.day ? null : cur))}
              onDrop={(e) => {
                e.preventDefault();
                setDropDay(null);
                const id = e.dataTransfer.getData("text/plain") || dragId;
                if (id) void block(id, d.day);
                setDragId(null);
              }}
              className={`glass min-h-[150px] rounded-xl p-2 transition-colors ${
                dropDay === d.day ? "ring-1 ring-ember-400/70" : ""
              } ${d.workday ? "" : "opacity-50"}`}
            >
              <p className="font-mono text-[10px] text-ink-500">
                {label} {d.day.slice(5)}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-ink-400">
                {d.workday ? fmtMin(d.planned_min) : "off"}
              </p>
              <ul className="mt-1.5 space-y-1">
                {d.task_ids.map((id) => {
                  const t = byId(id);
                  if (!t) return null;
                  return (
                    <li
                      key={id}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/plain", id);
                        setDragId(id);
                      }}
                      onDragEnd={() => setDragId(null)}
                      title={t.text}
                      className={`cursor-grab truncate rounded-md border border-white/[0.06] bg-ink-950/80 px-1.5 py-0.5 text-[10.5px] text-ink-200 active:cursor-grabbing ${
                        dragId === id ? "opacity-50" : ""
                      }`}
                    >
                      {t.text}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>

      {/* Unplanned tray */}
      <section className="glass-studio rounded-xl p-3">
        <span className="micro-label">Unplanned</span>
        {plan.unscheduled.length === 0 ? (
          <p className="mt-1 text-[11px] text-ink-600">everything fits this week</p>
        ) : (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {plan.unscheduled.map((id) => {
              const t = byId(id);
              if (!t) return null;
              return (
                <li
                  key={id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("text/plain", id);
                    setDragId(id);
                  }}
                  onDragEnd={() => setDragId(null)}
                  title="Drag onto a day to block time for it"
                  className="cursor-grab rounded-lg border border-dashed border-ink-700 bg-ink-950/70 px-2 py-1 text-[11px] text-ink-300 active:cursor-grabbing"
                >
                  {t.text}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}