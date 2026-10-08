import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { CaptureFrequencyStats } from "../types";
import { SparkIcon } from "./Icons";

interface Props {
  onToast?: (message: string, kind?: "ok" | "err") => void;
  refreshKey?: number;
}

export default function CaptureFrequencyCard({ onToast, refreshKey }: Props) {
  const [days, setDays] = useState<number>(30);
  const [stats, setStats] = useState<CaptureFrequencyStats | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    api.captureFrequency(days)
      .then(setStats)
      .catch((e) => onToast?.(String(e), "err"))
      .finally(() => setLoading(false));
  }, [days, onToast]);

  useEffect(load, [load, refreshKey]);

  if (!stats && loading) return <div className="shimmer h-48 rounded-2xl" />;
  if (!stats) return null;

  const maxDailyCount = Math.max(1, ...stats.notes_per_day.map((d) => d.count));

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Capture Frequency Stats">
      {/* Header */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ember-500/15 text-ember-400 ring-1 ring-white/10">
            <SparkIcon className="h-3.5 w-3.5" />
          </div>
          <div>
            <h2 className="text-xs font-semibold text-ink-100">Capture Frequency & Tag Trends</h2>
            <p className="text-[10px] text-ink-400">Notes captured per day and topic evolution over time (#163)</p>
          </div>
        </div>

        {/* Window Selector */}
        <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-0.5">
          {[7, 14, 30, 90].map((w) => (
            <button
              key={w}
              onClick={() => setDays(w)}
              className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                days === w
                  ? "bg-ember-500/20 text-ember-300 font-semibold"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {w}d
            </button>
          ))}
        </div>
      </div>

      {/* KPI Stats */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 mb-4">
        <div className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5">
          <span className="font-mono text-[10px] text-ink-500">total captures</span>
          <p className="mt-0.5 text-lg font-semibold text-ink-100">{stats.total_captures}</p>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5">
          <span className="font-mono text-[10px] text-ink-500">daily average</span>
          <p className="mt-0.5 text-lg font-semibold text-iris-300">{stats.avg_per_day} <span className="text-[10px] text-ink-500 font-normal">/ day</span></p>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5">
          <span className="font-mono text-[10px] text-ink-500">busiest day</span>
          <p className="mt-0.5 truncate text-xs font-semibold text-ink-200">
            {stats.busiest_day ? `${stats.busiest_day.day.slice(5)} (${stats.busiest_day.count})` : "—"}
          </p>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5">
          <span className="font-mono text-[10px] text-ink-500">peak capture hour</span>
          <p className="mt-0.5 text-lg font-semibold text-amber-300">
            {stats.peak_hour !== null ? `${String(stats.peak_hour).padStart(2, "0")}:00` : "—"}
          </p>
        </div>
      </div>

      {/* Daily Volume Bar Chart */}
      <div className="mb-4 rounded-xl border border-white/[0.06] bg-ink-950/30 p-3">
        <div className="mb-2 flex items-center justify-between text-[10px] text-ink-400">
          <span>Daily Capture Volume</span>
          <span className="font-mono text-[9px] text-ink-500">max: {maxDailyCount} / day</span>
        </div>

        <div className="flex h-16 items-end gap-1 overflow-x-auto pt-2" aria-label="Daily capture volume chart">
          {stats.notes_per_day.map((d) => {
            const hPct = (d.count / maxDailyCount) * 100;
            const textPct = d.count > 0 ? (d.text / d.count) * 100 : 0;
            const voicePct = d.count > 0 ? (d.voice / d.count) * 100 : 0;
            const ytPct = d.count > 0 ? (d.youtube / d.count) * 100 : 0;

            return (
              <div
                key={d.day}
                className="group relative flex-1 min-w-[6px] h-full flex flex-col justify-end"
                title={`${d.day}: ${d.count} captures (${d.text} text, ${d.voice} voice, ${d.youtube} youtube)`}
              >
                <div
                  className="w-full rounded-t-sm transition-all overflow-hidden flex flex-col-reverse group-hover:brightness-125"
                  style={{ height: `${Math.max(4, hPct)}%` }}
                >
                  {d.count === 0 ? (
                    <div className="w-full h-1 bg-white/[0.06]" />
                  ) : (
                    <>
                      {d.text > 0 && <div className="bg-iris-400" style={{ height: `${textPct}%` }} />}
                      {d.voice > 0 && <div className="bg-ember-400" style={{ height: `${voicePct}%` }} />}
                      {d.youtube > 0 && <div className="bg-rose-500" style={{ height: `${ytPct}%` }} />}
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="mt-2 flex items-center justify-center gap-4 text-[9px] text-ink-400 border-t border-white/[0.04] pt-2">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-iris-400" /> Text notes
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-ember-400" /> Voice notes
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" /> YouTube
          </span>
        </div>
      </div>

      {/* Top Tags Over Time */}
      <div>
        <div className="mb-2 flex items-center justify-between text-[11px] font-medium text-ink-200">
          <span>Top Tags Over Time</span>
          <span className="text-[10px] text-ink-500 font-normal">Topic frequency sparklines (#168)</span>
        </div>

        {stats.top_tags_over_time.length === 0 ? (
          <p className="text-[11px] text-ink-500">No tagged captures recorded in this window.</p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {stats.top_tags_over_time.map((tagItem) => {
              const maxTagDay = Math.max(1, ...tagItem.timeline.map((t) => t.count));
              return (
                <div
                  key={tagItem.tag}
                  className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5 flex flex-col justify-between"
                >
                  <div className="flex items-baseline justify-between mb-1.5">
                    <span className="truncate text-xs font-medium text-ink-100">#{tagItem.tag}</span>
                    <span className="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[9px] text-ink-400">
                      {tagItem.total}
                    </span>
                  </div>

                  {/* Sparkline bars */}
                  <div
                    className="flex h-5 items-end gap-[2px] pt-1"
                    title={`Timeline trend for #${tagItem.tag}`}
                  >
                    {tagItem.timeline.map((pt) => {
                      const barH = pt.count > 0 ? Math.max(15, (pt.count / maxTagDay) * 100) : 10;
                      return (
                        <div
                          key={pt.day}
                          className={`flex-1 rounded-[1px] transition-all ${
                            pt.count > 0 ? "bg-ember-400/80 hover:bg-ember-300" : "bg-white/[0.04]"
                          }`}
                          style={{ height: `${barH}%` }}
                          title={`${pt.day}: ${pt.count}`}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
