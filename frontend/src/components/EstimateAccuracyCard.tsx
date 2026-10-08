import { useEffect, useState } from "react";
import { api } from "../api";
import { ClockIcon } from "./Icons";
import type { EstimateAccuracyData } from "../types";

interface Props {
  refreshKey: number;
}

export default function EstimateAccuracyCard({ refreshKey }: Props) {
  const [data, setData] = useState<EstimateAccuracyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTasks, setShowTasks] = useState(false);

  useEffect(() => {
    setLoading(true);
    api
      .estimateAccuracy()
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [refreshKey]);

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-4">
        <div className="h-24 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (error || !data) {
    return null;
  }

  const {
    total_evaluated,
    untracked_count,
    total_estimated_min,
    total_spent_min,
    avg_error_min,
    overall_accuracy_pct,
    bias,
    counts,
    by_priority,
    items,
  } = data;

  const biasBadge = () => {
    switch (bias) {
      case "underestimating":
        return (
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-amber-300">
            Underestimating (tasks take longer)
          </span>
        );
      case "overestimating":
        return (
          <span className="rounded-full bg-cyan-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-cyan-300">
            Overestimating (tasks finish faster)
          </span>
        );
      case "accurate":
        return (
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-emerald-300">
            On Target
          </span>
        );
      default:
        return (
          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 font-mono text-[10px] text-ink-400">
            No focus data yet
          </span>
        );
    }
  };

  const totalCounts = counts.on_target + counts.underestimated + counts.overestimated || 1;
  const onTargetPct = Math.round((counts.on_target / totalCounts) * 100);
  const underPct = Math.round((counts.underestimated / totalCounts) * 100);
  const overPct = 100 - onTargetPct - underPct;

  return (
    <div
      data-testid="estimate-accuracy-card"
      className="glass-studio rounded-2xl border border-white/[0.06] p-4 text-xs"
    >
      {/* Header */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5">
        <div className="flex items-center gap-2">
          <ClockIcon className="h-4 w-4 text-amber-400" />
          <h3 className="font-semibold text-ink-100">Time-Estimate Accuracy</h3>
          <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
            #170
          </span>
        </div>
        {biasBadge()}
      </div>

      {total_evaluated === 0 ? (
        <div className="py-6 text-center text-ink-500">
          <p>No completed tasks with both estimated and actual focus time logged yet.</p>
          {untracked_count > 0 && (
            <p className="mt-1 text-[11px] text-ink-400">
              {untracked_count} task{untracked_count === 1 ? " has" : "s have"} estimates waiting for focus time logging.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3.5">
          {/* KPI grid */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
              <div className="text-[10px] uppercase tracking-wider text-ink-400">Accuracy</div>
              <div
                className={`mt-1 font-mono text-base font-semibold ${
                  overall_accuracy_pct >= 80
                    ? "text-emerald-300"
                    : overall_accuracy_pct >= 60
                    ? "text-amber-300"
                    : "text-rose-300"
                }`}
              >
                {overall_accuracy_pct}%
              </div>
            </div>

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
              <div className="text-[10px] uppercase tracking-wider text-ink-400">Est vs Actual</div>
              <div className="mt-1 font-mono text-xs font-semibold text-ink-200">
                <span className="text-iris-300">{total_estimated_min}m</span>
                <span className="mx-1 text-ink-600">/</span>
                <span className="text-ember-300">{total_spent_min}m</span>
              </div>
            </div>

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
              <div className="text-[10px] uppercase tracking-wider text-ink-400">Avg Error</div>
              <div className="mt-1 font-mono text-base font-semibold text-ink-200">
                ±{avg_error_min}m
              </div>
            </div>

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
              <div className="text-[10px] uppercase tracking-wider text-ink-400">Evaluated</div>
              <div className="mt-1 font-mono text-base font-semibold text-emerald-300">
                {total_evaluated}
              </div>
            </div>
          </div>

          {/* Distribution Bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-ink-400">
              <span>Estimation Distribution</span>
              <span className="font-mono text-[10px]">
                {counts.on_target} on target · {counts.underestimated} under · {counts.overestimated} over
              </span>
            </div>
            <div className="flex h-2 w-full overflow-hidden rounded-full bg-ink-900">
              {counts.on_target > 0 && (
                <div
                  style={{ width: `${onTargetPct}%` }}
                  className="bg-emerald-500 transition-all"
                  title={`On target: ${counts.on_target} (${onTargetPct}%)`}
                />
              )}
              {counts.underestimated > 0 && (
                <div
                  style={{ width: `${underPct}%` }}
                  className="bg-amber-500 transition-all"
                  title={`Underestimated (took longer): ${counts.underestimated} (${underPct}%)`}
                />
              )}
              {counts.overestimated > 0 && (
                <div
                  style={{ width: `${overPct}%` }}
                  className="bg-cyan-500 transition-all"
                  title={`Overestimated (finished faster): ${counts.overestimated} (${overPct}%)`}
                />
              )}
            </div>
          </div>

          {/* Priority Breakdown */}
          <div className="grid grid-cols-3 gap-2">
            {(["P1", "P2", "P3"] as const).map((prio) => {
              const pData = by_priority[prio];
              if (!pData || pData.count === 0) return null;
              return (
                <div
                  key={prio}
                  className="rounded-lg border border-white/[0.04] bg-white/[0.01] p-2 text-center"
                >
                  <div className="flex items-center justify-center gap-1">
                    <span className="font-mono text-[10px] font-semibold text-ink-300">{prio}</span>
                    <span className="text-[10px] text-ink-500">({pData.count})</span>
                  </div>
                  <div className="mt-1 font-mono text-xs text-ink-200">
                    {pData.accuracy_pct}% acc
                  </div>
                  <div className="mt-0.5 text-[9.5px] text-ink-400 font-mono">
                    {pData.estimated_min}m est / {pData.spent_min}m
                  </div>
                </div>
              );
            })}
          </div>

          {/* Toggle Tasks Details */}
          <div className="border-t border-white/[0.06] pt-2">
            <button
              onClick={() => setShowTasks((prev) => !prev)}
              className="flex w-full items-center justify-between text-[11px] font-medium text-ink-400 hover:text-ink-200"
            >
              <span>{showTasks ? "Hide evaluated tasks" : `Show evaluated tasks (${items.length})`}</span>
              <span>{showTasks ? "▲" : "▼"}</span>
            </button>

            {showTasks && (
              <div className="mt-2 max-h-48 space-y-1.5 overflow-y-auto pr-1">
                {items.map((task) => (
                  <div
                    key={task.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.04] bg-white/[0.01] p-1.5 text-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-ink-200">{task.text}</p>
                      <div className="flex items-center gap-2 font-mono text-[10px] text-ink-400">
                        <span>{task.priority}</span>
                        <span>·</span>
                        <span>Est: {task.estimate_min}m</span>
                        <span>·</span>
                        <span>Actual: {task.spent_min}m</span>
                      </div>
                    </div>
                    <div className="text-right font-mono text-[10.5px]">
                      <span
                        className={
                          task.status === "on_target"
                            ? "text-emerald-300"
                            : task.status === "underestimated"
                            ? "text-amber-300"
                            : "text-cyan-300"
                        }
                      >
                        {task.diff_min > 0 ? `+${task.diff_min}m` : `${task.diff_min}m`}
                      </span>
                      <div className="text-[9.5px] text-ink-500">{task.accuracy_pct}%</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
