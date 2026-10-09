import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ActivityIcon } from "./Icons";
import ChartExportButton from "./ChartExportButton";
import type { BurndownData, BurndownSeriesPoint } from "../types";

interface Props {
  refreshKey: number;
}

export default function BurndownChartCard({ refreshKey }: Props) {
  const [windowDays, setWindowDays] = useState<14 | 30 | 60>(30);
  const [data, setData] = useState<BurndownData | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoveredPoint, setHoveredPoint] = useState<BurndownSeriesPoint | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .burndown(windowDays)
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
        <div className="h-32 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  // Chart coordinate geometry
  const chartWidth = 600;
  const chartHeight = 180;
  const paddingX = 40;
  const paddingY = 24;

  const points = data.series;
  const maxVal = Math.max(
    1,
    ...points.map((p) => Math.max(p.open_backlog, p.ideal_burndown, p.added, p.resolved))
  );

  const getX = (idx: number) => {
    if (points.length <= 1) return paddingX;
    return paddingX + (idx / (points.length - 1)) * (chartWidth - paddingX * 2);
  };

  const getY = (val: number) => {
    return chartHeight - paddingY - (val / maxVal) * (chartHeight - paddingY * 2);
  };

  // Build actual backlog SVG path
  const actualPath = points
    .map((p, idx) => `${idx === 0 ? "M" : "L"} ${getX(idx).toFixed(1)} ${getY(p.open_backlog).toFixed(1)}`)
    .join(" ");

  // Build actual area path
  const areaPath = points.length > 0
    ? `${actualPath} L ${getX(points.length - 1).toFixed(1)} ${chartHeight - paddingY} L ${getX(0).toFixed(1)} ${chartHeight - paddingY} Z`
    : "";

  // Build ideal line path
  const idealPath = points
    .map((p, idx) => `${idx === 0 ? "M" : "L"} ${getX(idx).toFixed(1)} ${getY(p.ideal_burndown).toFixed(1)}`)
    .join(" ");

  return (
    <div
      role="region"
      aria-label="Backlog Burndown Chart"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
            <ActivityIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">Backlog Burndown</h3>
            <p className="text-xs text-ink-400">
              Unprocessed captures & open tasks trajectory
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            {([14, 30, 60] as const).map((days) => (
              <button
                key={days}
                onClick={() => setWindowDays(days)}
                className={`rounded-lg px-2.5 py-1 font-mono text-xs transition-colors ${
                  windowDays === days
                    ? "bg-amber-500/20 font-medium text-amber-300"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                {days}d
              </button>
            ))}
          </div>

          <ChartExportButton
            title={`burndown_${windowDays}d`}
            getSvg={() => svgRef.current}
          />
        </div>
      </div>

      {/* KPI Cards */}
      <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Current Backlog</div>
          <div className="mt-1 flex items-baseline gap-2 font-mono">
            <span className="text-xl font-bold text-amber-400">{data.current_backlog}</span>
            <span className="text-xs text-ink-400">
              ({data.current_open_tasks} tasks + {data.current_pending_captures} inbox)
            </span>
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Resolution Velocity</div>
          <div className="mt-1 flex items-baseline gap-2 font-mono">
            <span className="text-xl font-bold text-emerald-400">{data.avg_daily_resolved}</span>
            <span className="text-xs text-ink-400">resolved / day</span>
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Projected Clear</div>
          <div className="mt-1 flex items-baseline gap-2 font-mono">
            {data.current_backlog === 0 ? (
              <span className="text-sm font-semibold text-emerald-400">Zero Backlog Achieved!</span>
            ) : data.days_to_zero !== null ? (
              <>
                <span className="text-xl font-bold text-sky-400">~{data.days_to_zero}d</span>
                <span className="text-xs text-ink-400">
                  ({data.projected_date ? data.projected_date.slice(5) : ""})
                </span>
              </>
            ) : (
              <span className="text-xs text-ink-400">No velocity data</span>
            )}
          </div>
        </div>
      </div>

      {/* Visual Chart */}
      <div className="mt-5 space-y-2">
        <div className="relative overflow-hidden rounded-xl border border-white/[0.04] bg-black/30 p-2">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${chartWidth} ${chartHeight}`}
            className="w-full overflow-visible"
            aria-hidden="true"
          >
            <defs>
              <linearGradient id="burndownGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.25" />
                <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.0" />
              </linearGradient>
            </defs>

            {/* Grid lines */}
            {[0, 0.5, 1].map((ratio) => {
              const y = chartHeight - paddingY - ratio * (chartHeight - paddingY * 2);
              return (
                <line
                  key={ratio}
                  x1={paddingX}
                  y1={y}
                  x2={chartWidth - paddingX}
                  y2={y}
                  stroke="rgba(255,255,255,0.06)"
                  strokeDasharray="4 4"
                />
              );
            })}

            {/* Ideal burndown line (dashed) */}
            {idealPath && (
              <path
                d={idealPath}
                fill="none"
                stroke="rgba(255,255,255,0.3)"
                strokeDasharray="4 4"
                strokeWidth="1.5"
              />
            )}

            {/* Actual backlog area & line */}
            {areaPath && <path d={areaPath} fill="url(#burndownGrad)" />}
            {actualPath && (
              <path
                d={actualPath}
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}

            {/* Added / Resolved bar indicators per day */}
            {points.map((p, idx) => {
              const x = getX(idx);
              const barWidth = Math.max(2, (chartWidth - paddingX * 2) / (points.length * 3));
              const addH = (p.added / maxVal) * (chartHeight - paddingY * 2);
              const resH = (p.resolved / maxVal) * (chartHeight - paddingY * 2);
              const baseY = chartHeight - paddingY;

              return (
                <g key={p.day} className="cursor-pointer">
                  {p.added > 0 && (
                    <rect
                      x={x - barWidth - 1}
                      y={baseY - addH}
                      width={barWidth}
                      height={addH}
                      fill="#ef4444"
                      opacity="0.6"
                      rx="1"
                    />
                  )}
                  {p.resolved > 0 && (
                    <rect
                      x={x + 1}
                      y={baseY - resH}
                      width={barWidth}
                      height={resH}
                      fill="#10b981"
                      opacity="0.7"
                      rx="1"
                    />
                  )}
                  {/* Invisible hover trigger */}
                  <rect
                    x={x - barWidth * 2}
                    y={0}
                    width={barWidth * 4}
                    height={chartHeight}
                    fill="transparent"
                    onMouseEnter={() => setHoveredPoint(p)}
                    onMouseLeave={() => setHoveredPoint(null)}
                  />
                  {/* Point dot on hover */}
                  {hoveredPoint?.day === p.day && (
                    <circle
                      cx={x}
                      cy={getY(p.open_backlog)}
                      r="4"
                      fill="#f59e0b"
                      stroke="#ffffff"
                      strokeWidth="2"
                    />
                  )}
                </g>
              );
            })}
          </svg>

          {/* Hover tooltip */}
          {hoveredPoint && (
            <div className="absolute right-3 top-3 rounded-lg border border-white/10 bg-zinc-900/90 px-3 py-2 text-xs shadow-lg backdrop-blur">
              <div className="font-mono font-medium text-ink-200">{hoveredPoint.day}</div>
              <div className="mt-1 flex items-center gap-3 font-mono text-[11px]">
                <span className="text-amber-400">Backlog: {hoveredPoint.open_backlog}</span>
                <span className="text-rose-400">+{hoveredPoint.added}</span>
                <span className="text-emerald-400">-{hoveredPoint.resolved}</span>
              </div>
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-[11px] text-ink-400">
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-4 rounded-full bg-amber-400 inline-block" />
              Actual Backlog
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 border-b border-dashed border-white/40 inline-block" />
              Ideal Burndown
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-rose-500/80 inline-block" />
              Added
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm bg-emerald-500/80 inline-block" />
              Resolved
            </span>
          </div>

          <div className="font-mono text-[10px]">
            {points[0]?.day} → {points[points.length - 1]?.day}
          </div>
        </div>
      </div>
    </div>
  );
}
