import { useEffect, useId, useRef, useState } from "react";
import { appColor, fmtSecs, prettyAppName } from "../apps";
import { activationProps } from "./a11y";
import type { ActivitySession } from "../types";

/** Hook to measure container pixel width for 1:1 crisp SVG rendering without viewBox distortion. */
function useChartWidth(defaultW = 680): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(defaultW);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setWidth(Math.round(w));
    };
    update();
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        if (w > 0) setWidth(Math.round(w));
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, width];
}


function smoothPath(points: {x: number, y: number}[]): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M${points[0].x},${points[0].y}`;
  if (points.length === 2) return `M${points[0].x},${points[0].y} L${points[1].x},${points[1].y}`;
  
  let path = `M${points[0].x},${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = i > 0 ? points[i - 1] : points[0];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = i !== points.length - 2 ? points[i + 2] : p2;
    
    const tension = 0.15;
    const cp1x = p1.x + (p2.x - p0.x) * tension;
    const cp1y = p1.y + (p2.y - p0.y) * tension;
    const cp2x = p2.x - (p3.x - p1.x) * tension;
    const cp2y = p2.y - (p3.y - p1.y) * tension;
    
    path += ` C${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
  }
  return path;
}

/* ---------------- Bars (architectural columns, clean tracks, value labels, avg line) ---------------- */

export interface BarDatum {
  key?: string;
  label: string;
  value: number;
  sub?: string;
  hint?: string;
  color?: string;
}

interface BarsProps {
  data: BarDatum[];
  color?: string;
  height?: number;
  format?: (v: number) => string;
  highlightLast?: boolean;
  selectedIndex?: number | null;
  onSelect?: (index: number, item: BarDatum) => void;
  showAvg?: boolean;
}

export function Bars({
  data,
  color = "#c8643b",
  height = 104,
  format,
  highlightLast = true,
  selectedIndex = null,
  onSelect,
  showAvg = false,
}: BarsProps) {
  const uid = useId().replace(/:/g, "");
  const [containerRef, W] = useChartWidth(700);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  if (!data.length) return <ChartEmpty height={height} />;

  const H = Math.max(height, 64);
  const pad = { top: 18, right: 14, bottom: 22, left: 44 };
  const plotH = Math.max(16, H - pad.top - pad.bottom);
  const maxValue = Math.max(...data.map((d) => d.value), 1);
  const avg = data.length ? data.reduce((sum, d) => sum + d.value, 0) / data.length : 0;
  const n = Math.max(data.length, 1);
  const slot = (W - pad.left - pad.right) / n;
  const labelStep = Math.max(1, Math.ceil(n / 8));
  const fmt = (v: number) => (format ? format(v) : String(v));

  // Balanced column width: sleek architecture, never ballooning into giant eggs
  const barW =
    n <= 7
      ? Math.max(16, Math.min(Math.round(slot * 0.38), 24))
      : n <= 14
        ? Math.max(11, Math.min(Math.round(slot * 0.46), 16))
        : Math.max(6, Math.min(Math.round(slot * 0.58), 11));
  const rx = Math.min(5, Math.floor(barW / 2));

  return (
    <div ref={containerRef} className="chart-shell select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full overflow-visible"
        style={{ height }}
        role="img"
        aria-label="Bar chart"
      >
        <defs>
          <style>{`
            @keyframes bar-grow {
              0% { transform: scaleY(0); }
              100% { transform: scaleY(1); }
            }
            .bar-animate {
              animation: bar-grow 0.8s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
              transform-origin: bottom;
              transform-box: fill-box;
            }
            @keyframes fade-in {
              0% { opacity: 0; }
              100% { opacity: 1; }
            }
            .fade-in { animation: fade-in 0.4s ease-out forwards; }
          `}</style>
          <linearGradient id={`bar-grad-overlay-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.15" />
          </linearGradient>
          <filter id={`bar-glow-${uid}`}>
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
          {data.map((_, i) => {
            const x = pad.left + i * slot + (slot - barW) / 2;
            return (
              <clipPath key={`clip-${i}`} id={`bar-clip-${uid}-${i}`}>
                <rect x={x} y={pad.top} width={barW} height={plotH} rx={rx} />
              </clipPath>
            );
          })}
        </defs>

        {/* Gridlines & Y-Axis ticks */}
        {[0, 0.5, 1].map((p) => {
          const y = pad.top + plotH * p;
          return (
            <g key={p}>
              <line
                x1={pad.left}
                x2={W - pad.right}
                y1={y}
                y2={y}
                stroke="#e2e8f0"
                strokeWidth="1.5"
                strokeDasharray="1 4" strokeLinecap="round"
              />
              <text
                x={pad.left - 6}
                y={y + 3.5}
                textAnchor="end"
                fill="#64748b"
                fontSize="9"
                fontFamily="var(--font-mono)"
              >
                {fmt(Math.round(maxValue * (1 - p)))}
              </text>
            </g>
          );
        })}

        {/* Average reference line */}
        {showAvg && avg > 0 && (
          <g>
            <line
              x1={pad.left}
              x2={W - pad.right}
              y1={pad.top + plotH * (1 - avg / maxValue)}
              y2={pad.top + plotH * (1 - avg / maxValue)}
              stroke="#b55c3c"
              strokeWidth="1.2"
              strokeDasharray="4 3"
              opacity="0.85"
            />
            <text
              x={W - pad.right}
              y={pad.top + plotH * (1 - avg / maxValue) - 4}
              textAnchor="end"
              fill="#98452d"
              fontSize="8.5"
              fontFamily="var(--font-mono)"
              fontWeight="600"
            >
              AVG {fmt(Math.round(avg))}
            </text>
          </g>
        )}

        {/* Bars */}
        {data.map((d, i) => {
          const hasVal = d.value > 0;
          const barH = hasVal ? Math.max(3, Math.round((d.value / maxValue) * plotH)) : 0;
          const x = pad.left + i * slot + (slot - barW) / 2;
          const y = pad.top + plotH - barH;
          const isSelected = selectedIndex === i;
          const isHovered = hoverIndex === i;
          const isLast = highlightLast && i === data.length - 1;
          const active = isSelected || isHovered || isLast;
          const barColor = d.color ?? color;
          const labelVisible = n <= 10 || i % labelStep === 0 || i === n - 1;

          return (
            <g
              key={d.key ?? i}
              onMouseEnter={() => setHoverIndex(i)}
              onMouseLeave={() => setHoverIndex(null)}
              onClick={onSelect ? () => onSelect(i, d) : undefined}
              role={onSelect ? "button" : undefined}
              tabIndex={onSelect ? 0 : undefined}
              onKeyDown={
                onSelect
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(i, d);
                      }
                    }
                  : undefined
              }
              aria-label={`${d.label}: ${fmt(d.value)}`}
              className={onSelect ? "cursor-pointer" : ""}
            >
              {/* Invisible wider hit target for effortless scrubbing/clicking */}
              <rect
                x={pad.left + i * slot}
                y={pad.top - 10}
                width={slot}
                height={plotH + 20}
                fill="transparent"
              />

              {/* Recessed track */}
              <rect
                x={x}
                y={pad.top}
                width={barW}
                height={plotH}
                rx={rx}
                fill={isSelected ? "#e2e8f0" : "#f1f5f9"}
                stroke={isSelected ? "#2563eb" : "transparent"}
                strokeWidth={isSelected ? 1.5 : 0}
              />

              {/* Base line marker for empty slots */}
              {!hasVal && (
                <line
                  x1={x + 3}
                  x2={x + barW - 3}
                  y1={pad.top + plotH - 1}
                  y2={pad.top + plotH - 1}
                  stroke="#cbd5e1"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              )}

              {n <= 7 && isHovered && (
                <rect x={pad.left + i * slot + slot/2 - Math.max(barW + 12, 32)/2} y={pad.top - 6} width={Math.max(barW + 12, 32)} height={plotH + 12} rx="8" fill="rgba(15,23,42,0.04)" className="fade-in" />
              )}
              {/* Filled bar clipped inside track rounded bounds */}
              {hasVal && (
                <g className="bar-animate" style={{
                  transition: "opacity 0.16s ease",
                  opacity: selectedIndex !== null && selectedIndex !== i ? 0.35 : active ? 1 : 0.8
                }}>
                  <rect
                    x={x}
                    y={y}
                    width={barW}
                    height={barH}
                    rx={rx}
                    clipPath={`url(#bar-clip-${uid}-${i})`}
                    fill={barColor}
                    filter={isHovered ? `url(#bar-glow-${uid})` : undefined}
                    style={{ transition: "y 0.3s ease, height 0.3s ease" }}
                  />
                  <rect
                    x={x}
                    y={y}
                    width={barW}
                    height={barH}
                    rx={rx}
                    clipPath={`url(#bar-clip-${uid}-${i})`}
                    fill={`url(#bar-grad-overlay-${uid})`}
                    style={{ transition: "y 0.3s ease, height 0.3s ease" }}
                  />
                </g>
              )}

              {/* Direct formatted value label above bar for immediate glanceability */}
              {n <= 10 && hasVal && (
                <text
                  x={x + barW / 2}
                  y={Math.max(11, y - 4)}
                  textAnchor="middle"
                  fill={isSelected ? "#2563eb" : active ? "#0f172a" : "#475569"}
                  fontSize="9.5"
                  fontWeight={active ? "700" : "600"}
                  fontFamily="var(--font-mono)"
                >
                  {fmt(d.value)}
                </text>
              )}

              {/* Floating tooltip on hover when bar label isn't already explicit */}
              {isHovered && (
                <g className="pointer-events-none fade-in">
                  <rect
                    x={Math.min(W - 82, Math.max(pad.left, x + barW / 2 - 40))}
                    y={Math.max(0, y - 36)}
                    width="80"
                    height="32"
                    rx="8"
                    fill="#0f172ae6"
                    filter="drop-shadow(0 4px 12px rgba(0, 0, 0, 0.15))"
                  />
                  <text
                    x={Math.min(W - 42, Math.max(pad.left + 40, x + barW / 2))}
                    y={Math.max(12, y - 24)}
                    textAnchor="middle"
                    fill="#ffffff"
                    fontSize="10"
                    fontWeight="600"
                    fontFamily="var(--font-mono)"
                  >
                    {fmt(d.value)}
                  </text>
                  <text
                    x={Math.min(W - 42, Math.max(pad.left + 40, x + barW / 2))}
                    y={Math.max(24, y - 12)}
                    textAnchor="middle"
                    fill="#94a3b8"
                    fontSize="8.5"
                    fontWeight="500"
                    fontFamily="var(--font-sans)"
                  >
                    {d.label}
                  </text>
                </g>
              )}

              {/* X-axis day label */}
              {labelVisible && (
                <text
                  x={x + barW / 2}
                  y={H - 5}
                  textAnchor="middle"
                  fill={isSelected ? "#2563eb" : "#475569"}
                  fontSize="10"
                  fontWeight={isSelected ? "700" : "500"}
                  fontFamily="var(--font-sans)"
                >
                  {d.label}
                </text>
              )}

              <title>{[d.label, fmt(d.value), d.sub, d.hint].filter(Boolean).join(" · ")}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ChartEmpty({ height = 100, label = "No data for this period" }: { height?: number; label?: string }) {
  return <div className="chart-empty" style={{ height }}><span>{label}</span></div>;
}

/* ---------------- AreaTrend (smooth SVG curve + interactive scrub/click) ---------------- */

interface AreaTrendProps {
  data: BarDatum[];
  color?: string;
  height?: number;
  format?: (v: number) => string;
  selectedIndex?: number | null;
  onSelect?: (index: number, item: BarDatum) => void;
  showAvg?: boolean;
}

export function AreaTrend({
  data,
  color = "#74875c",
  height = 110,
  format,
  selectedIndex = null,
  onSelect,
  showAvg = true,
}: AreaTrendProps) {
  const uid = useId().replace(/:/g, "");
  const [containerRef, W] = useChartWidth(700);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const n = data.length;
  if (n === 0) return <ChartEmpty height={height} />;

  const fmt = (v: number) => (format ? format(v) : String(v));
  const H = height;
  const padX = 44;
  const padTop = 14;
  const padBot = 22;
  const plotW = Math.max(20, W - padX * 2);
  const plotH = Math.max(16, H - padTop - padBot);
  const max = Math.max(...data.map((d) => d.value), 1);
  const avg = data.reduce((s, d) => s + d.value, 0) / n;
  const step = Math.max(1, Math.ceil(n / 8));

  const pts = data.map((d, i) => {
    const x = n === 1 ? W / 2 : padX + (i / (n - 1)) * plotW;
    const y = padTop + plotH - (d.value / max) * plotH;
    return { x, y, d, i };
  });

  const linePath = smoothPath(pts);
  const areaPath = `${linePath} L${pts[n - 1].x},${H - padBot} L${pts[0].x},${H - padBot} Z`;
  const activeIdx = hoverIdx ?? selectedIndex;
  const activePt = activeIdx !== null && pts[activeIdx] ? pts[activeIdx] : null;
  const yAvg = padTop + plotH * (1 - avg / max);

  return (
    <div ref={containerRef} className="chart-shell select-none">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full overflow-visible"
        style={{ height }}
        onMouseLeave={() => setHoverIdx(null)}
        role="img"
        aria-label="Area trend chart"
      >
        <defs>
          <style>{`
            @keyframes bar-grow {
              0% { transform: scaleY(0); }
              100% { transform: scaleY(1); }
            }
            .bar-animate {
              animation: bar-grow 0.8s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
              transform-origin: bottom;
              transform-box: fill-box;
            }
            @keyframes fade-in {
              0% { opacity: 0; }
              100% { opacity: 1; }
            }
            .fade-in { animation: fade-in 0.4s ease-out forwards; }
          `}</style>
          <linearGradient id={`bar-grad-overlay-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.15" />
          </linearGradient>
          <filter id={`bar-glow-${uid}`}>
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
          <linearGradient id={`area-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Horizontal gridlines */}
        {[0, 0.5, 1].map((p) => {
          const y = padTop + plotH * p;
          return (
            <g key={p}>
              <line
                x1={padX}
                x2={W - padX}
                y1={y}
                y2={y}
                stroke="#e2e8f0"
                strokeWidth="1.5"
                strokeDasharray="1 4" strokeLinecap="round"
              />
              <text
                x={padX - 7}
                y={y + 3.5}
                textAnchor="end"
                fill="#64748b"
                fontSize="9"
                fontFamily="var(--font-mono)"
              >
                {fmt(Math.round(max * (1 - p)))}
              </text>
            </g>
          );
        })}

        {/* Avg line */}
        {showAvg && avg > 0 && (
          <g>
            <line
              x1={padX}
              x2={W - padX}
              y1={yAvg}
              y2={yAvg}
              stroke="#2563eb"
              strokeDasharray="4 3"
              strokeWidth="1.2"
              opacity="0.85"
            />
            <text
              x={W - padX}
              y={yAvg - 4}
              textAnchor="end"
              fill="#1e40af"
              fontSize="8.5"
              fontFamily="var(--font-mono)"
              fontWeight="600"
            >
              AVG {fmt(Math.round(avg))}
            </text>
          </g>
        )}

        <path d={areaPath} fill={`url(#area-${uid})`} className="fade-in" />
        <path
          d={linePath}
          fill="none"
          stroke={color}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="area-line-animate"
          filter={`url(#line-glow-${uid})`}
        />

        {activePt && (
          <line
            x1={activePt.x}
            x2={activePt.x}
            y1={padTop}
            y2={H - padBot}
            stroke={color}
            strokeDasharray="3 3"
            opacity="0.6"
          />
        )}

        {pts.map((p) => {
          const isAct = activeIdx === p.i;
          return (
            <g
              key={p.d.key ?? p.i}
              onMouseEnter={() => setHoverIdx(p.i)}
              onClick={onSelect ? () => onSelect(p.i, p.d) : undefined}
              role={onSelect ? "button" : undefined}
              tabIndex={onSelect ? 0 : undefined}
              onKeyDown={
                onSelect
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(p.i, p.d);
                      }
                    }
                  : undefined
              }
              className={onSelect ? "cursor-pointer" : ""}
              aria-label={`${p.d.label}: ${fmt(p.d.value)}`}
            >
              <circle cx={p.x} cy={p.y} r="14" fill="transparent" />
              <circle
                cx={p.x}
                cy={p.y}
                r={isAct ? 5 : 3.5}
                fill="#fffdf8"
                stroke={color}
                strokeWidth={isAct ? 2.5 : 1.8}
                className={isAct ? "dot-pulse" : ""}
                style={{ transition: "r 0.2s ease, stroke-width 0.2s ease" }}
              />
              {activePt?.i === p.i && (
                <g className="pointer-events-none">
                  <rect
                    x={Math.min(W - 86, Math.max(padX, p.x - 42))}
                    y={Math.max(0, p.y - 30)}
                    width="84"
                    height="22"
                    rx="6"
                    fill="#0f172ae6"
                    filter="drop-shadow(0 2px 5px rgb(0 0 0 / 0.18))"
                  />
                  <text
                    x={Math.min(W - 44, Math.max(padX + 42, p.x))}
                    y={Math.max(14, p.y - 15)}
                    textAnchor="middle"
                    fill="#ffffff"
                    fontSize="10"
                    fontWeight="600"
                    fontFamily="var(--font-mono)"
                  >
                    {fmt(p.d.value)}
                  </text>
                </g>
              )}
              <title>{[p.d.label, fmt(p.d.value), p.d.hint, p.d.sub].filter(Boolean).join(" · ")}</title>
            </g>
          );
        })}

        {pts.map(
          (p) =>
            (p.i % step === 0 || p.i === n - 1) && (
              <text
                key={`x${p.i}`}
                x={p.x}
                y={H - 5}
                textAnchor="middle"
                fill={selectedIndex === p.i ? "#2563eb" : "#475569"}
                fontSize="10"
                fontFamily="var(--font-sans)"
              >
                {p.d.label}
              </text>
            ),
        )}
      </svg>
    </div>
  );
}

/* ---------------- Donut (precision non-overlapping segmented ring) ---------------- */

export interface DonutSegment {
  key?: string;
  value: number;
  color: string;
  label?: string;
  formatted?: string;
}

interface DonutProps {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  centerTop: string;
  centerSub?: string;
  selectedKey?: string | null;
  onSelect?: (key: string) => void;
}

export function Donut({
  segments,
  size = 148,
  thickness = 14,
  centerTop,
  centerSub,
  selectedKey = null,
  onSelect,
}: DonutProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const nonZeroSegs = segments.filter((s) => s.value > 0);
  const total = Math.max(
    nonZeroSegs.reduce((s, x) => s + x.value, 0),
    1,
  );
  const r = (size - thickness - 8) / 2;
  const c = 2 * Math.PI * r;
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDrawn(true), 40);
    return () => clearTimeout(t);
  }, []);

  const activeKey = hoveredKey ?? selectedKey;
  const activeSeg = activeKey
    ? nonZeroSegs.find((s) => (s.key ?? s.label) === activeKey)
    : null;
  const activePct = activeSeg ? Math.round((activeSeg.value / total) * 100) : null;
  const gapPx = nonZeroSegs.length > 1 ? 3 : 0;

  let offset = 0;
  return (
    <div className="relative shrink-0 select-none" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90 overflow-visible">
        <defs>
          <filter id="inner-shadow">
            <feOffset dx="0" dy="1"/>
            <feGaussianBlur stdDeviation="1" result="offset-blur"/>
            <feComposite operator="out" in="SourceGraphic" in2="offset-blur" result="inverse"/>
            <feFlood floodColor="black" floodOpacity="0.15" result="color"/>
            <feComposite operator="in" in="color" in2="inverse" result="shadow"/>
            <feComposite operator="over" in="shadow" in2="SourceGraphic"/>
          </filter>
        </defs>
        {/* Outer & inner subtle dial rings */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(64,59,47,0.12)"
          strokeWidth={thickness}
          filter="url(#inner-shadow)"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r - thickness / 2 - 2}
          fill="none"
          stroke="rgba(64,59,47,0.06)"
          strokeWidth={1}
        />
        {drawn &&
          nonZeroSegs.map((seg, i) => {
            const segKey = seg.key ?? seg.label ?? String(i);
            const isAct = activeKey === segKey;
            const isDim = activeKey !== null && !isAct;
            const frac = seg.value / total;
            const arcLen = Math.max(frac * c - gapPx, 1.5);
            const el = (
              <circle
                key={segKey}
                cx={size / 2}
                cy={size / 2}
                r={r}
                fill="none"
                stroke={seg.color}
                strokeWidth={isAct ? thickness + 3 : thickness}
                strokeDasharray={`${arcLen} ${Math.max(0, c - arcLen)}`}
                strokeDashoffset={-offset}
                strokeLinecap="butt"
                onMouseEnter={() => setHoveredKey(segKey)}
                onMouseLeave={() => setHoveredKey(null)}
                onClick={onSelect ? () => onSelect(segKey) : undefined}
                className={onSelect ? "cursor-pointer" : ""}
                style={{
                  opacity: isDim ? 0.3 : 1,
                  filter: isAct ? `drop-shadow(0 0 8px ${seg.color}88)` : "none",
                  transition:
                    "stroke-dasharray 0.65s cubic-bezier(0.2,0.7,0.3,1), stroke-dashoffset 0.65s cubic-bezier(0.2,0.7,0.3,1), stroke-width 0.18s ease, opacity 0.18s ease",
                }}
              >
                <title>{seg.label}</title>
              </circle>
            );
            offset += frac * c;
            return el;
          })}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-3 text-center">
        {activeSeg ? (
          <>
            <span
              className="max-w-full truncate text-[10px] font-semibold tracking-wide uppercase"
              style={{ color: activeSeg.color }}
            >
              {prettyAppName(activeSeg.key ?? activeSeg.label ?? "")}
            </span>
            <span className="font-mono text-base font-bold tabular-nums text-ink-100">
              {activeSeg.formatted ?? `${activePct}%`}
            </span>
            <span className="font-mono text-[9.5px] text-ink-400">{activePct}% share</span>
          </>
        ) : (
          <>
            <span className="stat-number text-lg leading-tight">
              {centerTop}
            </span>
            {centerSub && <span className="mt-0.5 text-[10px] text-ink-400">{centerSub}</span>}
          </>
        )}
      </div>
      {nonZeroSegs.length === 0 && <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] text-ink-400">No activity yet</div>}
    </div>
  );
}

/* ---------------- Ring (single-value progress gauge) ---------------- */

export function Ring({
  progress,
  size = 88,
  thickness = 8,
  color = "#4b786b",
  label,
  sub,
}: {
  progress: number;
  size?: number;
  thickness?: number;
  color?: string;
  label?: string;
  sub?: string;
}) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.min(Math.max(progress, 0), 1);
  const [drawn, setDrawn] = useState(false);
  const [dispProgress, setDispProgress] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => setDrawn(true), 40);
    return () => clearTimeout(t);
  }, []);
  useEffect(() => {
    let start = performance.now();
    let frame: number;
    const animate = (now: number) => {
      const p = Math.min((now - start) / 800, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      setDispProgress(ease * clamped);
      if (p < 1) frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [clamped]);
  return (
    <div className="relative shrink-0 select-none" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90 overflow-visible">
        <defs>
          <linearGradient id={`ring-grad-overlay`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.1" />
          </linearGradient>
          <filter id="ring-inner-shadow">
            <feOffset dx="0" dy="1"/>
            <feGaussianBlur stdDeviation="1" result="offset-blur"/>
            <feComposite operator="out" in="SourceGraphic" in2="offset-blur" result="inverse"/>
            <feFlood floodColor="black" floodOpacity="0.15" result="color"/>
            <feComposite operator="in" in="color" in2="inverse" result="shadow"/>
            <feComposite operator="over" in="shadow" in2="SourceGraphic"/>
          </filter>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="rgba(64,59,47,0.12)"
          strokeWidth={thickness}
          filter="url(#ring-inner-shadow)"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={`${clamped * c} ${c}`}
          strokeDashoffset={drawn ? 0 : c}
          style={{
            filter: clamped > 0 ? `drop-shadow(0 0 6px ${color}66)` : "none",
            transition:
              "stroke-dasharray 0.85s cubic-bezier(0.2,0.7,0.3,1), stroke-dashoffset 0.4s",
          }}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="url(#ring-grad-overlay)"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={`${clamped * c} ${c}`}
          strokeDashoffset={drawn ? 0 : c}
          style={{
            transition:
              "stroke-dasharray 0.85s cubic-bezier(0.2,0.7,0.3,1), stroke-dashoffset 0.4s",
          }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {label ? <span className="font-mono text-sm font-bold tabular-nums text-ink-100">{label}</span> : <span className="font-mono text-sm font-bold tabular-nums text-ink-100">{Math.round(dispProgress * 100)}%</span>}
        {sub && <span className="text-[9px] font-medium uppercase tracking-wider text-ink-400">{sub}</span>}
      </div>
    </div>
  );
}

/* ---------------- Sparkline (area trend) ---------------- */

export function Spark({
  data,
  color = "#d8784c",
  width = 132,
  height = 34,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
}) {
  const uid = useId().replace(/:/g, "");
  const max = Math.max(...data, 1);
  const n = data.length;
  if (n < 2) return <div style={{ width, height }} />;
  const pts = data.map((v, i) => {
    const x = (i / (n - 1)) * (width - 6) + 3;
    const y = height - 4 - (v / max) * (height - 10);
    return [x, y] as const;
  });
  const line = smoothPath(pts.map(([x, y]) => ({x, y})));
  const area = `${line} L${pts[n - 1][0].toFixed(1)},${height} L${pts[0][0].toFixed(1)},${height} Z`;
  const gid = `sg-${uid}`;
  return (
    <svg width={width} height={height} className="overflow-visible">
      <defs>
          <style>{`
            @keyframes bar-grow {
              0% { transform: scaleY(0); }
              100% { transform: scaleY(1); }
            }
            .bar-animate {
              animation: bar-grow 0.8s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
              transform-origin: bottom;
              transform-box: fill-box;
            }
            @keyframes fade-in {
              0% { opacity: 0; }
              100% { opacity: 1; }
            }
            .fade-in { animation: fade-in 0.4s ease-out forwards; }
          `}</style>
          <linearGradient id={`bar-grad-overlay-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#ffffff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.15" />
          </linearGradient>
          <filter id={`bar-glow-${uid}`}>
            <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
            <feMerge>
              <feMergeNode in="coloredBlur"/>
              <feMergeNode in="SourceGraphic"/>
            </feMerge>
          </filter>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.38" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} style={{ animation: "fade-in 0.8s ease-out forwards" }} />
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={`spark-line-${uid}`}
      />
      <circle
        cx={pts[n - 1][0]}
        cy={pts[n - 1][1]}
        r="2.8"
        fill={color}
        className={`spark-dot-${uid}`}
      />
    </svg>
  );
}

/* ---------------- StackBar (interactive horizontal proportional bar) ---------------- */

export function StackBar({
  segments,
  height = 8,
  selectedKey = null,
  onSelect,
}: {
  segments: { key?: string; value: number; color: string; title?: string }[];
  height?: number;
  selectedKey?: string | null;
  onSelect?: (key: string) => void;
}) {
  const nonZero = segments.filter((s) => s.value > 0);
  const total = Math.max(
    nonZero.reduce((s, x) => s + x.value, 0),
    1,
  );
  const visualHeight = Math.max(height, 10);
  return (
    <div
      className="flex w-full gap-[2px] overflow-hidden rounded-full bg-white/[0.04] p-[2px] ring-1 ring-inset ring-white/[0.05]"
      style={{ height: visualHeight + 6 }}
    >
      {nonZero.map((s, i) => {
        const segKey = s.key ?? String(i);
        const isSel = selectedKey === segKey;
        const isDim = selectedKey !== null && !isSel;
        return (
          <div
            key={segKey}
            onClick={onSelect && s.key ? () => onSelect(s.key!) : undefined}
            onKeyDown={onSelect && s.key ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(s.key!); } } : undefined}
            className={`group relative h-full transition-all duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] rounded-full ${
              onSelect && s.key ? "cursor-pointer hover:brightness-125 hover:z-10" : ""
            }`}
            role={onSelect && s.key ? "button" : undefined}
            tabIndex={onSelect && s.key ? 0 : undefined}
            aria-label={s.title ?? `${segKey}: ${Math.round((s.value / total) * 100)}%`}
            style={{
              width: `${(s.value / total) * 100}%`,
              background: s.color,
              opacity: isDim ? 0.28 : 1,
              boxShadow: isSel ? `0 0 10px ${s.color}` : "none",
            }}
          >
            <div className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 opacity-0 transition-opacity group-hover:opacity-100 z-50 whitespace-nowrap rounded-md bg-[#0f172ae6] px-2.5 py-1 text-[10px] font-semibold text-white shadow-md backdrop-blur-sm">
              {s.title ?? segKey} · {Math.round((s.value / total) * 100)}%
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------- SessionRibbon (24-hour horizontal Gantt strip) ---------------- */

/** #339 a note captured or a task finished, pinned to its hour. */
export interface TimelineMarker {
  kind: "task" | "note";
  id: string;
  at: string;
  label: string;
}

interface SessionRibbonProps {
  sessions: ActivitySession[];
  selectedApp?: string | null;
  onSelectApp?: (app: string) => void;
  isToday?: boolean;
  markers?: TimelineMarker[];
  onMarkerClick?: (marker: TimelineMarker) => void;
}

export function SessionRibbon({
  sessions,
  selectedApp = null,
  onSelectApp,
  isToday = false,
  markers = [],
  onMarkerClick,
}: SessionRibbonProps) {
  const [hovered, setHovered] = useState<ActivitySession | null>(null);

  // Convert ISO timestamp to fractional hour (0..24)
  const toHourFrac = (iso: string) => {
    const d = new Date(iso);
    return d.getHours() + d.getMinutes() / 60 + d.getSeconds() / 3600;
  };

  const nowFrac = (() => {
    const d = new Date();
    return d.getHours() + d.getMinutes() / 60;
  })();

  const hhmm = (iso: string) =>
    new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="select-none">
      <div className="relative h-12 w-full overflow-hidden rounded-xl border border-ink-800 bg-ink-900 shadow-inner">
        {/* Subtle 1-hour bottom tick marks */}
        {Array.from({ length: 23 }, (_, idx) => idx + 1).map((h) => (
          <div
            key={h}
            className={`pointer-events-none absolute bottom-0 ${
              h % 4 === 0
                ? "top-0 border-l border-dotted border-ink-700/40"
                : "h-1.5 border-l border-ink-700/30"
            }`}
            style={{ left: `${(h / 24) * 100}%` }}
          />
        ))}

        {/* Session blocks — clamped to actual active duration so overnight idle gaps never stretch across hours */}
        {sessions.map((s) => {
          const startH = Math.max(0, Math.min(24, toHourFrac(s.first_seen)));
          const endRaw = Math.max(startH, Math.min(24, toHourFrac(s.last_seen)));
          const activeHours = Math.max(s.seconds / 3600, 0.08);
          const wallHours = Math.max(0, endRaw - startH);
          // If wall-clock span is much larger than active time (e.g., laptop slept/idled),
          // size the block by activeHours rather than the idle gap.
          const spanHours =
            wallHours > activeHours * 2.2
              ? Math.min(wallHours, Math.max(activeHours * 1.35, 0.14))
              : Math.max(wallHours, activeHours, 0.12);
          const leftPct = (startH / 24) * 100;
          const widthPct = Math.min(100 - leftPct, (spanHours / 24) * 100);
          const color = appColor(s.app_class);
          const isSel = selectedApp === s.app_class;
          const isDim = selectedApp !== null && !isSel;

          return (
            <div
              key={s.id}
              onMouseEnter={() => setHovered(s)}
              onMouseLeave={() => setHovered(null)}
              onClick={onSelectApp ? () => onSelectApp(s.app_class) : undefined}
              {...(onSelectApp
                ? activationProps(
                    `${prettyAppName(s.app_class)}, ${fmtSecs(s.seconds)} active`,
                    () => onSelectApp(s.app_class),
                  )
                : {})}
              className={`group absolute top-2 bottom-2 rounded-md transition-all ${
                onSelectApp ? "cursor-pointer hover:brightness-125 hover:z-20" : ""
              }`}
              style={{
                left: `${leftPct}%`,
                width: `${Math.max(widthPct, 0.42)}%`,
                background: `linear-gradient(180deg, ${color}e6 0%, ${color} 100%)`,
                opacity: isDim ? 0.18 : 0.94,
                boxShadow: isSel ? `0 2px 9px ${color}66` : "inset 0 1px 0 rgba(255,255,255,0.2), 0 1px 2px rgba(38,57,47,.16)",
              }}
            >
              <div className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 opacity-0 transition-opacity group-hover:opacity-100 z-50 whitespace-nowrap rounded-md bg-[#0f172af2] px-2.5 py-1.5 text-[10px] text-white shadow-lg backdrop-blur-sm">
                <div className="font-semibold" style={{ color: color }}>{prettyAppName(s.app_class)}</div>
                <div className="max-w-[200px] truncate text-slate-300 my-0.5">{s.title || "(untitled window)"}</div>
                <div className="font-mono text-[9px] text-blue-300">{hhmm(s.first_seen)} · {fmtSecs(s.seconds)} active</div>
              </div>
            </div>
          );
        })}

        {/* #339 notes captured and tasks finished, pinned to the hour they
            happened — the answer to "what did I do about this?" sits next to
            the work it belongs to. */}
        {markers.map((m, idx) => (
          <button
            key={`${m.kind}-${m.id}-${idx}`}
            onClick={onMarkerClick ? () => onMarkerClick(m) : undefined}
            title={`${m.label} — ${hhmm(m.at)}`}
            aria-label={`${m.kind}: ${m.label} at ${hhmm(m.at)}`}
            className="absolute top-0.5 z-10 h-2.5 w-2.5 -translate-x-1/2 rounded-full border border-ink-950/70 shadow-[0_1px_3px_rgba(0,0,0,.5)] transition-transform hover:scale-125"
            style={{
              left: `${(Math.max(0, Math.min(24, toHourFrac(m.at))) / 24) * 100}%`,
              background: m.kind === "task" ? "#4ade80" : "#a78bfa",
            }}
          />
        ))}

        {sessions.length === 0 && <div className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-ink-400">No tracked sessions for this day</div>}

        {/* Current time indicator needle for today */}
        {isToday && (
          <div
            className="pointer-events-none absolute top-0 bottom-0 z-20 w-[2px] bg-ember-500 shadow-[0_0_7px_#bd5d38]"
            style={{ left: `${(nowFrac / 24) * 100}%` }}
          >
            <span className="absolute -top-0.5 -left-[3px] h-2 w-2 rotate-45 bg-ember-400" />
          </div>
        )}
      </div>

      {/* Axis & hover inspection bar */}
      <div className="mt-1.5 flex h-4 items-center justify-between font-mono text-[9.5px] text-ink-400">
        {hovered ? (
          <div className="flex w-full items-center gap-2 text-[11px] text-ink-200">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ background: appColor(hovered.app_class) }}
            />
            <span className="font-semibold" style={{ color: appColor(hovered.app_class) }}>
              {prettyAppName(hovered.app_class)}
            </span>
            <span className="truncate text-ink-300">{hovered.title || "(untitled window)"}</span>
            <span className="ml-auto shrink-0 font-mono text-[10.5px] tabular-nums text-ember-300">
              {hhmm(hovered.first_seen)} · {fmtSecs(hovered.seconds)} active
            </span>
          </div>
        ) : (
          <>
            <span>00:00</span>
            <span>04:00</span>
            <span>08:00</span>
            <span>12:00</span>
            <span>16:00</span>
            <span>20:00</span>
            <span>24:00</span>
          </>
        )}
      </div>
    </div>
  );
}
