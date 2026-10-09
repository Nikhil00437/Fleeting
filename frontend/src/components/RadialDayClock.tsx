import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ChevronLeftIcon, ChevronRightIcon, ClockIcon } from "./Icons";
import ChartExportButton from "./ChartExportButton";
import type { RadialClockData, RadialClockSegment } from "../types";

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180.0;
  return {
    x: cx + r * Math.sin(rad),
    y: cy - r * Math.cos(rad),
  };
}

function describeArc(
  cx: number,
  cy: number,
  rIn: number,
  rOut: number,
  startDeg: number,
  endDeg: number
) {
  const span = Math.min(359.99, Math.max(0.5, endDeg - startDeg));
  const effectiveEnd = startDeg + span;

  const p1 = polarToCartesian(cx, cy, rOut, startDeg);
  const p2 = polarToCartesian(cx, cy, rOut, effectiveEnd);
  const p3 = polarToCartesian(cx, cy, rIn, effectiveEnd);
  const p4 = polarToCartesian(cx, cy, rIn, startDeg);

  const largeArcFlag = span > 180 ? 1 : 0;

  return [
    `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`,
    `A ${rOut} ${rOut} 0 ${largeArcFlag} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`,
    `L ${p3.x.toFixed(2)} ${p3.y.toFixed(2)}`,
    `A ${rIn} ${rIn} 0 ${largeArcFlag} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

const PALETTE = [
  "#38bdf8", // Sky
  "#f59e0b", // Amber
  "#a855f7", // Purple
  "#10b981", // Emerald
  "#ec4899", // Pink
  "#6366f1", // Indigo
  "#f97316", // Orange
  "#14b8a6", // Teal
  "#ef4444", // Rose
  "#84cc16", // Lime
];

interface Props {
  refreshKey: number;
  initialDay?: string;
  onSelectDay?: (day: string) => void;
}

function shiftDay(dayStr: string, deltaDays: number): string {
  const [y, m, d] = dayStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d + deltaDays);
  const yyyy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function getTodayStr(): string {
  const dt = new Date();
  const yyyy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function RadialDayClock({ refreshKey, initialDay, onSelectDay }: Props) {
  const todayStr = useMemo(() => getTodayStr(), []);
  const [day, setDay] = useState(initialDay || todayStr);
  const [data, setData] = useState<RadialClockData | null>(null);
  const [loading, setLoading] = useState(true);
  const [colorMode, setColorMode] = useState<"app" | "project">("app");
  const [hoveredSegment, setHoveredSegment] = useState<RadialClockSegment | null>(null);
  const [hoveredHour, setHoveredHour] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (initialDay && initialDay !== day) {
      setDay(initialDay);
    }
  }, [initialDay]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .radialClock(day)
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
  }, [day, refreshKey]);

  const handlePrevDay = () => {
    const newDay = shiftDay(day, -1);
    setDay(newDay);
    onSelectDay?.(newDay);
  };

  const handleNextDay = () => {
    const newDay = shiftDay(day, 1);
    setDay(newDay);
    onSelectDay?.(newDay);
  };

  const handleToday = () => {
    setDay(todayStr);
    onSelectDay?.(todayStr);
  };

  // Build color mapping
  const colorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (!data) return map;
    const keys =
      colorMode === "app"
        ? data.apps.map((a) => a.app)
        : data.projects.map((p) => p.project);

    keys.forEach((k, idx) => {
      map.set(k, PALETTE[idx % PALETTE.length]);
    });
    return map;
  }, [data, colorMode]);

  const getSegmentColor = (seg: RadialClockSegment) => {
    const key = colorMode === "app" ? seg.app_class : seg.project;
    return colorMap.get(key) || "#94a3b8";
  };

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-5">
        <div className="h-64 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  const cx = 180;
  const cy = 180;
  const rOuter = 145;
  const rInner = 100;
  const rHourIn = 72;
  const rHourOutMax = 94;

  const daytimePct =
    data.total_seconds > 0
      ? Math.round((data.daytime_seconds / data.total_seconds) * 100)
      : 0;
  const nightPct = 100 - daytimePct;

  return (
    <div
      role="region"
      aria-label="24-hour radial day clock"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500/10 text-sky-400">
            <ClockIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">
              24-Hour Radial Day Clock
            </h3>
            <p className="text-xs text-ink-400">
              Activity distribution around the 24-hour dial
            </p>
          </div>
        </div>

        {/* Controls: Prev/Next/Today & Color Mode */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Color Mode Toggle */}
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            <button
              onClick={() => setColorMode("app")}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                colorMode === "app"
                  ? "bg-sky-500/20 font-medium text-sky-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              By App
            </button>
            <button
              onClick={() => setColorMode("project")}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                colorMode === "project"
                  ? "bg-sky-500/20 font-medium text-sky-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              By Project
            </button>
          </div>

          {/* Day Navigation */}
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            <button
              onClick={handlePrevDay}
              aria-label="Previous day"
              className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
            >
              <ChevronLeftIcon className="h-4 w-4" />
            </button>
            <span className="px-2 font-mono text-xs text-ink-200">{day}</span>
            <button
              onClick={handleNextDay}
              aria-label="Next day"
              className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
            >
              <ChevronRightIcon className="h-4 w-4" />
            </button>
            {day !== todayStr && (
              <button
                onClick={handleToday}
                className="ml-1 rounded-lg px-2 py-0.5 text-[11px] text-ink-400 hover:text-ink-100"
              >
                Today
              </button>
            )}
          </div>

          {/* Chart Export Action (#253) */}
          <ChartExportButton
            title={`radial_day_clock_${day}`}
            getSvg={() => svgRef.current}
          />
        </div>
      </div>

      {/* Main Content Area */}
      <div className="mt-5 grid grid-cols-1 items-center gap-6 lg:grid-cols-12">
        {/* SVG Radial Clock Visual */}
        <div className="flex justify-center lg:col-span-7">
          <div className="relative w-full max-w-[360px] aspect-square">
            <svg
              ref={svgRef}
              viewBox="0 0 360 360"
              className="w-full h-full overflow-visible select-none"
              aria-hidden="true"
            >
              <defs>
                {/* Dial background gradient */}
                <radialGradient id="clockDialGrad" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#1e1e24" stopOpacity="0.4" />
                  <stop offset="90%" stopColor="#0c0d12" stopOpacity="0.8" />
                  <stop offset="100%" stopColor="#050508" stopOpacity="1" />
                </radialGradient>
              </defs>

              {/* Dial base */}
              <circle
                cx={cx}
                cy={cy}
                r={168}
                fill="url(#clockDialGrad)"
                stroke="rgba(255,255,255,0.06)"
                strokeWidth="1"
              />

              {/* Background day/night ambient sectors */}
              {/* Daytime: 06:00 to 18:00 (90 deg to 270 deg) */}
              <path
                d={describeArc(cx, cy, rInner - 10, rOuter + 8, 90, 270)}
                fill="#f59e0b"
                fillOpacity="0.03"
              />
              {/* Nighttime: 18:00 to 06:00 (270 deg to 90 deg) */}
              <path
                d={describeArc(cx, cy, rInner - 10, rOuter + 8, 270, 450)}
                fill="#38bdf8"
                fillOpacity="0.02"
              />

              {/* 24-Hour Markers and Ticks */}
              {Array.from({ length: 24 }).map((_, h) => {
                const deg = (h / 24) * 360;
                const isMajor = h % 3 === 0;
                const tickLen = isMajor ? 8 : 4;
                const pStart = polarToCartesian(cx, cy, 158 - tickLen, deg);
                const pEnd = polarToCartesian(cx, cy, 158, deg);
                const pLabel = polarToCartesian(cx, cy, 168, deg);

                return (
                  <g key={`marker-${h}`}>
                    <line
                      x1={pStart.x}
                      y1={pStart.y}
                      x2={pEnd.x}
                      y2={pEnd.y}
                      stroke={isMajor ? "rgba(255,255,255,0.3)" : "rgba(255,255,255,0.1)"}
                      strokeWidth={isMajor ? 1.5 : 1}
                    />
                    {isMajor && (
                      <text
                        x={pLabel.x}
                        y={pLabel.y}
                        textAnchor="middle"
                        dominantBaseline="central"
                        className="fill-ink-400 font-mono text-[9px] font-semibold"
                      >
                        {String(h).padStart(2, "0")}
                      </text>
                    )}
                  </g>
                );
              })}

              {/* Hourly Intensity Radial Ring */}
              {data.hourly.map((hb) => {
                const startDeg = (hb.hour / 24) * 360;
                const endDeg = ((hb.hour + 1) / 24) * 360;
                const ratio = Math.min(1.0, hb.seconds / 3600);
                const rOut = rHourIn + ratio * (rHourOutMax - rHourIn);
                const isHovered = hoveredHour === hb.hour;

                if (hb.seconds <= 0) return null;

                return (
                  <path
                    key={`hour-${hb.hour}`}
                    d={describeArc(cx, cy, rHourIn, rOut, startDeg + 0.5, endDeg - 0.5)}
                    fill={isHovered ? "#38bdf8" : "rgba(255,255,255,0.15)"}
                    className="cursor-pointer transition-colors"
                    onMouseEnter={() => setHoveredHour(hb.hour)}
                    onMouseLeave={() => setHoveredHour(null)}
                  />
                );
              })}

              {/* Activity Session Arc Segments */}
              {data.segments.map((seg) => {
                const color = getSegmentColor(seg);
                const isHovered = hoveredSegment?.id === seg.id;
                const currentROuter = isHovered ? rOuter + 4 : rOuter;
                const currentRInner = isHovered ? rInner - 3 : rInner;

                return (
                  <path
                    key={`seg-${seg.id}-${seg.start_time}`}
                    d={describeArc(
                      cx,
                      cy,
                      currentRInner,
                      currentROuter,
                      seg.start_deg,
                      seg.end_deg
                    )}
                    fill={color}
                    fillOpacity={isHovered ? 0.95 : 0.75}
                    stroke={isHovered ? "#ffffff" : "rgba(0,0,0,0.4)"}
                    strokeWidth={isHovered ? 1.5 : 0.5}
                    className="cursor-pointer transition-all duration-150"
                    onMouseEnter={() => setHoveredSegment(seg)}
                    onMouseLeave={() => setHoveredSegment(null)}
                  />
                );
              })}

              {/* Center Hub */}
              <circle
                cx={cx}
                cy={cy}
                r={64}
                fill="#121319"
                stroke="rgba(255,255,255,0.08)"
                strokeWidth="1.5"
              />

              {/* Center Hub Text Content */}
              {hoveredSegment ? (
                <g className="pointer-events-none select-none">
                  <text
                    x={cx}
                    y={cy - 22}
                    textAnchor="middle"
                    className="fill-sky-400 font-mono text-[10px] font-semibold"
                  >
                    {hoveredSegment.start_time} – {hoveredSegment.end_time}
                  </text>
                  <text
                    x={cx}
                    y={cy - 5}
                    textAnchor="middle"
                    className="fill-white font-semibold text-[11px]"
                  >
                    {colorMode === "app"
                      ? hoveredSegment.app_class
                      : hoveredSegment.project}
                  </text>
                  <text
                    x={cx}
                    y={cy + 12}
                    textAnchor="middle"
                    className="fill-emerald-400 font-mono text-[10px] font-bold"
                  >
                    {fmtSecs(hoveredSegment.seconds)}
                  </text>
                  <text
                    x={cx}
                    y={cy + 26}
                    textAnchor="middle"
                    className="fill-ink-400 text-[8px] max-w-[80px] truncate"
                  >
                    {hoveredSegment.title.slice(0, 16)}
                  </text>
                </g>
              ) : hoveredHour !== null ? (
                <g className="pointer-events-none select-none">
                  <text
                    x={cx}
                    y={cy - 16}
                    textAnchor="middle"
                    className="fill-ink-400 font-mono text-[10px]"
                  >
                    Hour {String(hoveredHour).padStart(2, "0")}:00
                  </text>
                  <text
                    x={cx}
                    y={cy + 4}
                    textAnchor="middle"
                    className="fill-white font-mono text-xs font-bold"
                  >
                    {fmtSecs(data.hourly[hoveredHour].seconds)} active
                  </text>
                  <text
                    x={cx}
                    y={cy + 20}
                    textAnchor="middle"
                    className="fill-sky-400 text-[9px]"
                  >
                    {data.hourly[hoveredHour].top_app || "No activity"}
                  </text>
                </g>
              ) : (
                <g className="pointer-events-none select-none">
                  <text
                    x={cx}
                    y={cy - 16}
                    textAnchor="middle"
                    className="fill-ink-400 text-[9px] uppercase tracking-wider font-semibold"
                  >
                    Active Screentime
                  </text>
                  <text
                    x={cx}
                    y={cy + 6}
                    textAnchor="middle"
                    className="fill-white font-mono text-base font-bold"
                  >
                    {fmtSecs(data.total_seconds)}
                  </text>
                  <text
                    x={cx}
                    y={cy + 22}
                    textAnchor="middle"
                    className="fill-ink-400 font-mono text-[9px]"
                  >
                    ☀️ {daytimePct}% · 🌙 {nightPct}%
                  </text>
                </g>
              )}
            </svg>
          </div>
        </div>

        {/* Side Panel: Breakdown & Legend */}
        <div className="space-y-4 lg:col-span-5">
          {/* Quick Metrics */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-2.5">
              <span className="text-[10px] text-ink-400">Peak Hour</span>
              <div className="mt-0.5 font-mono text-sm font-semibold text-amber-300">
                {String(data.peak_hour).padStart(2, "0")}:00
              </div>
            </div>

            <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-2.5">
              <span className="text-[10px] text-ink-400">Daytime / Night</span>
              <div className="mt-0.5 font-mono text-sm font-semibold text-sky-300">
                {fmtSecs(data.daytime_seconds)} / {fmtSecs(data.night_seconds)}
              </div>
            </div>
          </div>

          {/* Top Breakdown Items */}
          <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
            <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-400">
              Top {colorMode === "app" ? "Applications" : "Projects"}
            </div>

            <div className="space-y-2">
              {(colorMode === "app" ? data.apps : data.projects).slice(0, 6).map((item) => {
                const name = "app" in item ? item.app : item.project;
                const color = colorMap.get(name) || "#94a3b8";

                return (
                  <div key={name} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2 overflow-hidden pr-2">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-full"
                        style={{ backgroundColor: color }}
                      />
                      <span className="truncate font-medium text-ink-200">{name}</span>
                    </div>

                    <div className="flex items-center gap-2 font-mono text-[11px] shrink-0">
                      <span className="text-ink-400">{item.pct}%</span>
                      <span className="font-semibold text-ink-100">{fmtSecs(item.seconds)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="text-[11px] text-ink-400 leading-relaxed">
            Hover over any session arc or hour ring on the 24-hour dial to inspect its exact time range, application, and window context.
          </div>
        </div>
      </div>
    </div>
  );
}
