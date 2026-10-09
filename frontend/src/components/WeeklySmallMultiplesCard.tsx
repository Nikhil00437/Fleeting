import { useEffect, useState } from "react";
import { api } from "../api";
import { ActivityIcon, ChevronLeftIcon, ChevronRightIcon } from "./Icons";
import type { WeeklySmallMultiplesData } from "../types";

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function shiftWeek(dateStr: string, deltaWeeks: number): string {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d + deltaWeeks * 7);
  const yyyy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

interface Props {
  refreshKey: number;
  onSelectDay?: (day: string) => void;
}

export default function WeeklySmallMultiplesCard({ refreshKey, onSelectDay }: Props) {
  const [weekStart, setWeekStart] = useState<string>("");
  const [data, setData] = useState<WeeklySmallMultiplesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoveredHour, setHoveredHour] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .weeklySmallMultiples(weekStart || undefined)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          if (!weekStart) {
            setWeekStart(res.week_start);
          }
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
  }, [weekStart, refreshKey]);

  const handlePrevWeek = () => {
    if (data?.week_start) {
      setWeekStart(shiftWeek(data.week_start, -1));
    }
  };

  const handleNextWeek = () => {
    if (data?.week_start) {
      setWeekStart(shiftWeek(data.week_start, 1));
    }
  };

  const handleThisWeek = () => {
    setWeekStart("");
  };

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-5">
        <div className="h-56 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  const maxVal = Math.max(1800, data.max_hourly_seconds);
  const chartHeight = 64;
  const chartWidth = 140;

  return (
    <div
      role="region"
      aria-label="Weekly Small-Multiples"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
            <ActivityIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">
              Weekly Small-Multiples
            </h3>
            <p className="text-xs text-ink-400">
              Side-by-side comparison of hourly focus across all seven days
            </p>
          </div>
        </div>

        {/* Controls: Prev / Next / This Week */}
        <div className="flex items-center gap-1.5 rounded-xl bg-black/20 p-1">
          <button
            onClick={handlePrevWeek}
            aria-label="Previous week"
            className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
          >
            <ChevronLeftIcon className="h-4 w-4" />
          </button>
          <span className="px-2 font-mono text-xs text-ink-200">
            {data.week_start} → {data.week_end}
          </span>
          <button
            onClick={handleNextWeek}
            aria-label="Next week"
            className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
          >
            <ChevronRightIcon className="h-4 w-4" />
          </button>
          <button
            onClick={handleThisWeek}
            className="ml-1 rounded-lg px-2 py-0.5 text-[11px] text-ink-400 hover:text-ink-100"
          >
            This Week
          </button>
        </div>
      </div>

      {/* Week Overview KPIs */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs border-b border-white/[0.04] pb-3">
        <div className="flex items-center gap-4">
          <span className="text-ink-400">
            Week Screentime:{" "}
            <strong className="font-mono text-emerald-400">
              {fmtSecs(data.total_seconds)}
            </strong>
          </span>
          <span className="text-ink-400">
            Daily Average:{" "}
            <strong className="font-mono text-ink-200">
              {fmtSecs(data.avg_daily_seconds)}
            </strong>
          </span>
        </div>

        <div className="font-mono text-[11px] text-ink-400">
          Shared scale: {Math.round(maxVal / 60)}m max/hr
        </div>
      </div>

      {/* 7 Synchronized Small-Multiples Columns */}
      <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7">
        {data.days.map((d) => {
          const isSelected = d.is_today;

          return (
            <div
              key={d.day}
              onClick={() => onSelectDay?.(d.day)}
              className={`group flex flex-col justify-between rounded-xl border p-2.5 transition-all cursor-pointer ${
                isSelected
                  ? "border-emerald-500/30 bg-emerald-500/[0.04] shadow-sm"
                  : "border-white/[0.05] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]"
              }`}
            >
              {/* Day Header */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-baseline gap-1.5">
                    <span
                      className={`text-xs font-bold ${
                        isSelected ? "text-emerald-400" : "text-ink-100"
                      }`}
                    >
                      {d.day_of_week}
                    </span>
                    <span className="font-mono text-[10px] text-ink-400">
                      {d.day.slice(5)}
                    </span>
                  </div>

                  {d.focus_score > 0 && (
                    <span
                      className={`rounded px-1.5 py-0.2 font-mono text-[9px] font-semibold ${
                        d.focus_score >= 80
                          ? "bg-emerald-500/15 text-emerald-300"
                          : d.focus_score >= 60
                          ? "bg-amber-500/15 text-amber-300"
                          : "bg-white/[0.06] text-ink-400"
                      }`}
                    >
                      {d.focus_score}
                    </span>
                  )}
                </div>

                <div className="mt-1 flex items-baseline justify-between font-mono text-[11px]">
                  <span className="font-semibold text-ink-200">
                    {d.total_seconds > 0 ? fmtSecs(d.total_seconds) : "—"}
                  </span>
                  {d.top_app && (
                    <span className="max-w-[70px] truncate text-[9px] text-ink-400 font-sans">
                      {d.top_app}
                    </span>
                  )}
                </div>
              </div>

              {/* Synchronized Mini Hourly Bar Chart */}
              <div className="mt-3 relative h-16 w-full">
                <svg
                  viewBox={`0 0 ${chartWidth} ${chartHeight}`}
                  className="w-full h-full overflow-visible select-none"
                  aria-hidden="true"
                >
                  {/* Subtle 6h and 18h guide ticks */}
                  {[6, 12, 18].map((h) => {
                    const x = (h / 24) * chartWidth;
                    return (
                      <line
                        key={`guide-${h}`}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={chartHeight}
                        stroke="rgba(255,255,255,0.04)"
                        strokeDasharray="2 2"
                      />
                    );
                  })}

                  {/* Hourly activity bars */}
                  {d.hourly.map((secs, h) => {
                    const barW = Math.max(2, chartWidth / 24 - 1.2);
                    const x = (h / 24) * chartWidth;
                    const hRatio = Math.min(1.0, secs / maxVal);
                    const barH = Math.max(secs > 0 ? 3 : 0, hRatio * (chartHeight - 4));
                    const y = chartHeight - barH;
                    const isHovered = hoveredHour === h;

                    return (
                      <g key={`bar-${h}`}>
                        {secs > 0 && (
                          <rect
                            x={x}
                            y={y}
                            width={barW}
                            height={barH}
                            rx="1"
                            fill={
                              isHovered
                                ? "#34d399"
                                : isSelected
                                ? "#10b981"
                                : "#38bdf8"
                            }
                            opacity={isHovered ? 1 : 0.75}
                            className="transition-colors"
                          />
                        )}

                        {/* Interactive invisible hover column */}
                        <rect
                          x={x}
                          y={0}
                          width={chartWidth / 24}
                          height={chartHeight}
                          fill="transparent"
                          onMouseEnter={() => setHoveredHour(h)}
                          onMouseLeave={() => setHoveredHour(null)}
                        />
                      </g>
                    );
                  })}

                  {/* Synchronized Hover Guideline */}
                  {hoveredHour !== null && (
                    <line
                      x1={(hoveredHour / 24) * chartWidth + (chartWidth / 48)}
                      y1={0}
                      x2={(hoveredHour / 24) * chartWidth + (chartWidth / 48)}
                      y2={chartHeight}
                      stroke="#34d399"
                      strokeWidth="1.5"
                      opacity="0.8"
                    />
                  )}
                </svg>

                {/* Hover details tooltip for hovered hour */}
                {hoveredHour !== null && (
                  <div className="pointer-events-none absolute -top-5 left-1/2 -translate-x-1/2 rounded bg-black/80 px-1 py-0.5 font-mono text-[9px] text-emerald-300">
                    {hoveredHour}h: {Math.round(d.hourly[hoveredHour] / 60)}m
                  </div>
                )}
              </div>

              {/* Time Axis Labels */}
              <div className="mt-1 flex justify-between font-mono text-[8px] text-ink-500">
                <span>0h</span>
                <span>12h</span>
                <span>24h</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
