import { useEffect, useState } from "react";
import { api } from "../api";
import { CalendarIcon, CheckIcon, PlayIcon, TaskIcon } from "./Icons";
import type { TaskFunnelData, TaskFunnelStage } from "../types";

interface Props {
  refreshKey: number;
}

export default function TaskFunnelCard({ refreshKey }: Props) {
  const [windowDays, setWindowDays] = useState<number | null>(30);
  const [data, setData] = useState<TaskFunnelData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .taskFunnel(windowDays ?? undefined)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [windowDays, refreshKey]);

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-4">
        <div className="h-28 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  const stageIcon = (stageId: TaskFunnelStage["stage"]) => {
    switch (stageId) {
      case "captured":
        return <TaskIcon className="h-4 w-4 text-ink-300" />;
      case "planned":
        return <CalendarIcon className="h-4 w-4 text-sky-400" />;
      case "started":
        return <PlayIcon className="h-4 w-4 text-amber-400" />;
      case "completed":
        return <CheckIcon className="h-4 w-4 text-emerald-400" />;
    }
  };

  const stageColor = (stageId: TaskFunnelStage["stage"]) => {
    switch (stageId) {
      case "captured":
        return "from-ink-500/80 to-ink-600/80";
      case "planned":
        return "from-sky-500/80 to-sky-600/80";
      case "started":
        return "from-amber-500/80 to-amber-600/80";
      case "completed":
        return "from-emerald-500/80 to-emerald-600/80";
    }
  };

  const completedStage = data.stages.find((s) => s.stage === "completed");
  const overallRate = completedStage ? completedStage.pct_of_captured : 0;

  return (
    <div
      role="region"
      aria-label="Task Conversion Funnel"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ember-500/10 text-ember-400">
            <TaskIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">Task Conversion Funnel</h3>
            <p className="text-xs text-ink-400">
              Pipeline conversion from capture to completion ({data.total_tasks} tasks)
            </p>
          </div>
        </div>

        {/* Window controls */}
        <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
          {([7, 30, 90, null] as const).map((days) => (
            <button
              key={days ?? "all"}
              onClick={() => setWindowDays(days)}
              className={`rounded-lg px-2.5 py-1 font-mono text-xs transition-colors ${
                windowDays === days
                  ? "bg-ember-500/20 font-medium text-ember-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {days ? `${days}d` : "All"}
            </button>
          ))}
        </div>
      </div>

      {data.total_tasks === 0 ? (
        <div className="py-8 text-center text-xs text-ink-400">
          No tasks recorded for this time window.
        </div>
      ) : (
        <div className="mt-5 space-y-5">
          {/* Top highlight metric */}
          <div className="flex items-baseline justify-between rounded-xl bg-white/[0.02] px-4 py-2.5">
            <span className="text-xs font-medium text-ink-300">Completion Conversion Rate</span>
            <span className="font-mono text-lg font-bold text-emerald-400">
              {overallRate}%
            </span>
          </div>

          {/* Stepped visual funnel */}
          <div className="space-y-3">
            {data.stages.map((stage, idx) => {
              const widthPct = Math.max(12, stage.pct_of_captured);
              return (
                <div key={stage.stage} className="group">
                  <div className="flex items-center justify-between text-xs pb-1">
                    <div className="flex items-center gap-2">
                      {stageIcon(stage.stage)}
                      <span className="font-medium text-ink-200">{stage.name}</span>
                    </div>
                    <div className="flex items-center gap-3 font-mono">
                      <span className="text-ink-100 font-semibold">{stage.count}</span>
                      <span className="text-ink-400">({stage.pct_of_captured}%)</span>
                    </div>
                  </div>

                  {/* Progress / funnel bar */}
                  <div className="h-4 w-full overflow-hidden rounded-md bg-white/[0.04]">
                    <div
                      className={`h-full rounded-md bg-gradient-to-r ${stageColor(
                        stage.stage
                      )} transition-all duration-300`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>

                  {/* Dropoff between steps */}
                  {idx < data.stages.length - 1 && (
                    <div className="flex items-center gap-1.5 py-1 px-2 text-[10px] text-ink-400">
                      <span className="text-rose-400">↓</span>
                      <span>
                        {data.stages[idx + 1].dropoff_pct}% drop-off to next stage
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Breakdown by priority */}
          {Object.keys(data.by_priority).length > 0 && (
            <div className="border-t border-white/[0.06] pt-4">
              <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-400">
                Conversion by Priority
              </div>
              <div className="grid grid-cols-3 gap-2">
                {(["P1", "P2", "P3"] as const).map((prio) => {
                  const stat = data.by_priority[prio];
                  if (!stat || stat.captured === 0) return null;
                  const rate =
                    stat.captured > 0
                      ? Math.round((stat.completed / stat.captured) * 100)
                      : 0;
                  const prioBadge =
                    prio === "P1"
                      ? "text-rose-300 bg-rose-500/10 border-rose-500/20"
                      : prio === "P2"
                      ? "text-amber-300 bg-amber-500/10 border-amber-500/20"
                      : "text-ink-300 bg-ink-500/10 border-ink-500/20";

                  return (
                    <div
                      key={prio}
                      className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-2.5 text-center"
                    >
                      <div className="flex items-center justify-center gap-1.5 pb-1">
                        <span
                          className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${prioBadge}`}
                        >
                          {prio}
                        </span>
                      </div>
                      <div className="font-mono text-sm font-bold text-ink-100">
                        {rate}%
                      </div>
                      <div className="text-[10px] text-ink-400">
                        {stat.completed} / {stat.captured} done
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
