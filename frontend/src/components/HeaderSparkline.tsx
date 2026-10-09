import { useState, useId } from "react";

export interface SparklinePoint {
  label: string;
  value: number;
}

export interface HeaderSparklineProps {
  data: (SparklinePoint | number)[];
  width?: number;
  height?: number;
  color?: "amber" | "emerald" | "sky" | "violet" | "rose" | "ink";
  label?: string;
  unit?: string;
  className?: string;
}

const COLOR_MAP = {
  amber: { stroke: "#f59e0b", fill: "#f59e0b", text: "text-amber-400" },
  emerald: { stroke: "#10b981", fill: "#10b981", text: "text-emerald-400" },
  sky: { stroke: "#38bdf8", fill: "#38bdf8", text: "text-sky-400" },
  violet: { stroke: "#a855f7", fill: "#a855f7", text: "text-violet-400" },
  rose: { stroke: "#f43f5e", fill: "#f43f5e", text: "text-rose-400" },
  ink: { stroke: "#94a3b8", fill: "#94a3b8", text: "text-ink-300" },
};

export default function HeaderSparkline({
  data,
  width = 76,
  height = 22,
  color = "amber",
  label = "Recent trend",
  unit = "",
  className = "",
}: HeaderSparklineProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const gradId = useId();

  // Normalize points
  const points: SparklinePoint[] = data.map((item, idx) => {
    if (typeof item === "number") {
      return { label: `Day ${idx + 1}`, value: item };
    }
    return item;
  });

  const palette = COLOR_MAP[color] || COLOR_MAP.amber;

  if (points.length === 0) {
    return (
      <div
        className={`inline-flex items-center gap-1.5 opacity-40 ${className}`}
        aria-hidden="true"
      >
        <svg width={width} height={height} className="overflow-visible">
          <line
            x1={2}
            y1={height / 2}
            x2={width - 2}
            y2={height / 2}
            stroke="rgba(255,255,255,0.15)"
            strokeDasharray="2 2"
          />
        </svg>
      </div>
    );
  }

  const paddingX = 4;
  const paddingY = 4;
  const values = points.map((p) => p.value);
  const maxVal = Math.max(1, ...values);
  const total = values.reduce((s, v) => s + v, 0);
  const latest = points[points.length - 1].value;

  const coords = points.map((p, idx) => {
    const x =
      points.length <= 1
        ? width / 2
        : paddingX + (idx / (points.length - 1)) * (width - paddingX * 2);
    const y =
      height - paddingY - (p.value / maxVal) * (height - paddingY * 2);
    return { x, y, ...p };
  });

  const pathD = coords
    .map((c, idx) => `${idx === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`)
    .join(" ");

  const areaD =
    coords.length > 0
      ? `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${height - 1} L ${coords[0].x.toFixed(1)} ${height - 1} Z`
      : "";

  const activePoint = hoveredIdx !== null ? coords[hoveredIdx] : null;

  return (
    <div
      role="img"
      aria-label={`${label}: total ${total}${unit ? ` ${unit}` : ""}, latest ${latest}`}
      className={`group relative inline-flex items-center gap-1.5 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2 py-0.5 transition-colors hover:border-white/[0.12] hover:bg-white/[0.04] ${className}`}
      onMouseLeave={() => setHoveredIdx(null)}
    >
      <div className="relative">
        <svg
          width={width}
          height={height}
          className="overflow-visible select-none"
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const relX = e.clientX - rect.left;
            let closestIdx = 0;
            let minDiff = Infinity;
            coords.forEach((c, idx) => {
              const diff = Math.abs(c.x - relX);
              if (diff < minDiff) {
                minDiff = diff;
                closestIdx = idx;
              }
            });
            setHoveredIdx(closestIdx);
          }}
        >
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={palette.fill} stopOpacity="0.3" />
              <stop offset="100%" stopColor={palette.fill} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Area fill */}
          {areaD && <path d={areaD} fill={`url(#${gradId})`} />}

          {/* Line stroke */}
          {pathD && (
            <path
              d={pathD}
              fill="none"
              stroke={palette.stroke}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Current / last dot */}
          {coords.length > 0 && hoveredIdx === null && (
            <circle
              cx={coords[coords.length - 1].x}
              cy={coords[coords.length - 1].y}
              r="2.5"
              fill={palette.stroke}
            />
          )}

          {/* Hover indicator dot */}
          {activePoint && (
            <circle
              cx={activePoint.x}
              cy={activePoint.y}
              r="3.5"
              fill="#ffffff"
              stroke={palette.stroke}
              strokeWidth="1.5"
            />
          )}
        </svg>

        {/* Hover Popover Tooltip */}
        {activePoint && (
          <div className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-zinc-950/95 px-2 py-0.5 text-[10px] shadow-xl backdrop-blur">
            <span className="font-medium text-ink-300">{activePoint.label}: </span>
            <span className={`font-mono font-bold ${palette.text}`}>
              {activePoint.value}
            </span>
            {unit && <span className="text-ink-400"> {unit}</span>}
          </div>
        )}
      </div>

      {/* Summary value */}
      <span className="font-mono text-[10px] font-semibold text-ink-300">
        {latest}
      </span>
    </div>
  );
}
