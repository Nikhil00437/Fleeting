import { useEffect, useState } from "react";
import { api } from "../api";
import { ActivityIcon, SparkIcon } from "./Icons";
import type { DailyFocusScore, FocusScoreTrend } from "../types";

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${String(m).padStart(2, "0")}m` : `${h}h`;
}

interface Props {
  refreshKey: number;
  onSelectDay?: (day: string) => void;
}

export default function FocusScoreCard({ refreshKey, onSelectDay }: Props) {
  const [windowDays, setWindowDays] = useState<7 | 14 | 30>(14);
  const [trend, setTrend] = useState<FocusScoreTrend | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .focusScoreTrend(windowDays)
      .then((res) => {
        setTrend(res);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, [windowDays, refreshKey]);

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-4">
        <div className="h-24 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!trend) return null;

  const latestDay: DailyFocusScore | undefined = trend.days[trend.days.length - 1];
  const latestScore = latestDay?.score ?? 0;
  const latestGrade = latestDay?.grade ?? "Rest / Inactive";

  const gradeColor = (score: number) => {
    if (score >= 80) return "text-emerald-300";
    if (score >= 60) return "text-amber-300";
    if (score >= 40) return "text-orange-300";
    if (score > 0) return "text-rose-300";
    return "text-ink-500";
  };

  const barBg = (score: number) => {
    if (score >= 80) return "bg-emerald-500/80 hover:bg-emerald-400";
    if (score >= 60) return "bg-amber-500/80 hover:bg-amber-400";
    if (score >= 40) return "bg-orange-500/80 hover:bg-orange-400";
    if (score > 0) return "bg-rose-500/80 hover:bg-rose-400";
    return "bg-white/[0.05] hover:bg-white/[0.1]";
  };

  const directionBadge = () => {
    switch (trend.direction) {
      case "improving":
        return (
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-emerald-300">
            ↑ Improving
          </span>
        );
      case "declining":
        return (
          <span className="rounded-full bg-rose-500/15 px-2 py-0.5 font-mono text-[10px] font-medium text-rose-300">
            ↓ Declining
          </span>
        );
      default:
        return (
          <span className="rounded-full bg-white/[0.06] px-2 py-0.5 font-mono text-[10px] text-ink-300">
            → Stable
          </span>
        );
    }
  };

  return (
    <div
      data-testid="focus-score-card"
      className="glass-studio rounded-2xl border border-white/[0.06] p-4 text-xs"
    >
      {/* Header */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-2.5">
        <div className="flex items-center gap-2">
          <ActivityIcon className="h-4 w-4 text-emerald-400" />
          <h3 className="font-semibold text-ink-100">Daily Focus Score Trend</h3>
          <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
            #57
          </span>
        </div>

        <div className="flex items-center gap-2">
          {directionBadge()}
          <div className="flex rounded-lg border border-white/[0.06] bg-ink-950/80 p-0.5 text-[10px]">
            {([7, 14, 30] as const).map((r) => (
              <button
                key={r}
                onClick={() => setWindowDays(r)}
                className={`rounded-md px-2 py-0.5 font-mono transition-colors ${
                  windowDays === r
                    ? "bg-emerald-500/20 font-semibold text-emerald-300"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                {r}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
          <div className="text-[10px] uppercase tracking-wider text-ink-400">Today Score</div>
          <div className={`mt-1 font-mono text-base font-semibold ${gradeColor(latestScore)}`}>
            {latestScore}/100
          </div>
          <div className="text-[9.5px] text-ink-500">{latestGrade}</div>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
          <div className="text-[10px] uppercase tracking-wider text-ink-400">Average Score</div>
          <div className="mt-1 font-mono text-base font-semibold text-ink-100">
            {trend.average_score}
          </div>
          <div className="text-[9.5px] text-ink-500">across {trend.active_days_count} active days</div>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
          <div className="text-[10px] uppercase tracking-wider text-ink-400">Focus Streak</div>
          <div className="mt-1 flex items-center justify-center gap-1 font-mono text-base font-semibold text-amber-300">
            <SparkIcon className="h-3.5 w-3.5" />
            <span>{trend.streak_days} days</span>
          </div>
          <div className="text-[9.5px] text-ink-500">score ≥ 50</div>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-center">
          <div className="text-[10px] uppercase tracking-wider text-ink-400">Best Day</div>
          <div className="mt-1 font-mono text-base font-semibold text-emerald-300">
            {trend.best_day ? `${trend.best_day.score}/100` : "—"}
          </div>
          <div className="text-[9.5px] text-ink-500 font-mono">
            {trend.best_day ? trend.best_day.day.slice(5) : "no data"}
          </div>
        </div>
      </div>

      {/* Focus Trend Mini Chart */}
      <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.01] p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="micro-label">Focus Score Trend ({windowDays} Days)</span>
          <span className="font-mono text-[10px] text-ink-400">0 to 100</span>
        </div>

        <div className="flex h-20 items-end gap-1 overflow-x-auto pt-2">
          {trend.days.map((d) => {
            const hPct = Math.max(d.score, 4);
            return (
              <div
                key={d.day}
                onClick={() => onSelectDay?.(d.day)}
                className="group relative flex flex-1 min-w-[14px] cursor-pointer flex-col items-center"
              >
                <div
                  style={{ height: `${hPct}%` }}
                  className={`w-full rounded-t-xs transition-all ${barBg(d.score)}`}
                  title={`${d.day}: ${d.score}/100 (${d.grade}) · ${fmtSecs(d.total_seconds)}`}
                />
              </div>
            );
          })}
        </div>

        <div className="mt-1 flex justify-between font-mono text-[9px] text-ink-500">
          <span>{trend.days[0]?.day.slice(5)}</span>
          <span>{trend.days[trend.days.length - 1]?.day.slice(5)}</span>
        </div>
      </div>

      {/* Components Breakdown for Latest Day */}
      {latestDay && latestDay.total_seconds > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-white/[0.06] pt-2.5">
          <div className="rounded-lg bg-white/[0.02] p-2 text-center">
            <div className="text-[9.5px] text-ink-400 uppercase tracking-wider">Duration</div>
            <div className="font-mono font-medium text-ink-200">
              {latestDay.components.duration}/40 pts
            </div>
            <div className="font-mono text-[9px] text-ink-500">
              {fmtSecs(latestDay.total_seconds)} (target 4h)
            </div>
          </div>
          <div className="rounded-lg bg-white/[0.02] p-2 text-center">
            <div className="text-[9.5px] text-ink-400 uppercase tracking-wider">Stretch</div>
            <div className="font-mono font-medium text-ink-200">
              {latestDay.components.stretch}/35 pts
            </div>
            <div className="font-mono text-[9px] text-ink-500">
              {latestDay.seconds_per_switch
                ? `${Math.round(latestDay.seconds_per_switch / 60)}m avg stretch`
                : "unbroken"}
            </div>
          </div>
          <div className="rounded-lg bg-white/[0.02] p-2 text-center">
            <div className="text-[9.5px] text-ink-400 uppercase tracking-wider">Projects</div>
            <div className="font-mono font-medium text-ink-200">
              {latestDay.components.project}/25 pts
            </div>
            <div className="font-mono text-[9px] text-ink-500">
              {fmtSecs(latestDay.project_seconds)} on projects
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
