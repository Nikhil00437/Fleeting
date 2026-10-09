import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { FolderIcon, GridIcon } from "./Icons";
import ChartExportButton from "./ChartExportButton";
import ChartPalettePicker from "./ChartPalettePicker";
import { useChartPalette } from "../chartPalettes";
import type { ProjectTreemapData } from "../types";

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export interface TreemapRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function squarify<T extends { seconds: number }>(
  items: T[],
  bounds: TreemapRect
): (T & TreemapRect)[] {
  if (items.length === 0) return [];
  const totalVal = items.reduce((s, it) => s + it.seconds, 0);
  if (totalVal <= 0) return [];

  const area = bounds.w * bounds.h;
  const scaled = items.map((it) => ({
    ...it,
    area: (it.seconds / totalVal) * area,
  }));

  const results: (T & TreemapRect)[] = [];
  layoutRow(scaled, [], bounds, results);
  return results;
}

function layoutRow<T extends { seconds: number; area: number }>(
  items: T[],
  currentRow: T[],
  bounds: TreemapRect,
  out: (any & TreemapRect)[]
) {
  if (items.length === 0) {
    if (currentRow.length > 0) {
      renderRow(currentRow, bounds, out);
    }
    return;
  }

  const next = items[0];
  const shorterSide = Math.min(bounds.w, bounds.h);

  if (currentRow.length === 0) {
    layoutRow(items.slice(1), [next], bounds, out);
    return;
  }

  const currentWorst = worstRatio(currentRow, shorterSide);
  const candidateWorst = worstRatio([...currentRow, next], shorterSide);

  if (candidateWorst <= currentWorst) {
    layoutRow(items.slice(1), [...currentRow, next], bounds, out);
  } else {
    const remainingBounds = renderRow(currentRow, bounds, out);
    layoutRow(items, [], remainingBounds, out);
  }
}

function worstRatio<T extends { area: number }>(row: T[], length: number): number {
  if (length <= 0 || row.length === 0) return Infinity;
  const sumArea = row.reduce((s, it) => s + it.area, 0);
  const side = sumArea / length;
  if (side <= 0) return Infinity;

  let maxRatio = 0;
  for (const it of row) {
    const itemLength = it.area / side;
    const ratio = Math.max(side / itemLength, itemLength / side);
    if (ratio > maxRatio) maxRatio = ratio;
  }
  return maxRatio;
}

function renderRow<T extends { area: number }>(
  row: T[],
  bounds: TreemapRect,
  out: (any & TreemapRect)[]
): TreemapRect {
  const sumArea = row.reduce((s, it) => s + it.area, 0);
  const horizontal = bounds.w >= bounds.h;
  const length = horizontal ? bounds.h : bounds.w;
  const thickness = length > 0 ? sumArea / length : 0;

  let offset = 0;
  for (const it of row) {
    const itemLen = thickness > 0 ? it.area / thickness : 0;
    if (horizontal) {
      out.push({
        ...it,
        x: bounds.x,
        y: bounds.y + offset,
        w: thickness,
        h: itemLen,
      });
      offset += itemLen;
    } else {
      out.push({
        ...it,
        x: bounds.x + offset,
        y: bounds.y,
        w: itemLen,
        h: thickness,
      });
      offset += itemLen;
    }
  }

  if (horizontal) {
    return {
      x: bounds.x + thickness,
      y: bounds.y,
      w: Math.max(0, bounds.w - thickness),
      h: bounds.h,
    };
  } else {
    return {
      x: bounds.x,
      y: bounds.y + thickness,
      w: bounds.w,
      h: Math.max(0, bounds.h - thickness),
    };
  }
}

const PROJECT_PALETTE = [
  { fill: "#0369a1", border: "#38bdf8", bg: "rgba(14, 165, 233, 0.15)", text: "#7dd3fc" }, // Sky
  { fill: "#b45309", border: "#fbbf24", bg: "rgba(245, 158, 11, 0.15)", text: "#fde68a" }, // Amber
  { fill: "#6d28d9", border: "#c084fc", bg: "rgba(168, 85, 247, 0.15)", text: "#e9d5ff" }, // Purple
  { fill: "#047857", border: "#34d399", bg: "rgba(16, 185, 129, 0.15)", text: "#a7f3d0" }, // Emerald
  { fill: "#be185d", border: "#f472b6", bg: "rgba(236, 72, 153, 0.15)", text: "#fbcfe8" }, // Pink
  { fill: "#4338ca", border: "#818cf8", bg: "rgba(99, 102, 241, 0.15)", text: "#c7d2fe" }, // Indigo
  { fill: "#c2410c", border: "#fb923c", bg: "rgba(249, 115, 22, 0.15)", text: "#fed7aa" }, // Orange
  { fill: "#0f766e", border: "#2dd4bf", bg: "rgba(20, 184, 166, 0.15)", text: "#99f6e4" }, // Teal
];

interface Props {
  refreshKey: number;
  onSelectProject?: (project: string) => void;
}

export default function ProjectTreemapCard({ refreshKey, onSelectProject }: Props) {
  const [windowDays, setWindowDays] = useState<1 | 7 | 30>(7);
  const [data, setData] = useState<ProjectTreemapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoveredNode, setHoveredNode] = useState<{
    project: string;
    app?: string;
    seconds: number;
    pct: number;
  } | null>(null);
  const { paletteId, colors } = useChartPalette();
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .projectTreemap({ days: windowDays })
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

  // Compute Layout Geometry
  const layout = useMemo(() => {
    if (!data || data.projects.length === 0) return [];
    const totalW = 680;
    const totalH = 340;

    const projectBoxes = squarify(data.projects, { x: 0, y: 0, w: totalW, h: totalH });

    return projectBoxes.map((pBox, pIdx) => {
      const palette =
        paletteId === "default"
          ? PROJECT_PALETTE[pIdx % PROJECT_PALETTE.length]
          : {
              fill: colors[pIdx % colors.length],
              border: colors[pIdx % colors.length],
              bg: `${colors[pIdx % colors.length]}26`,
              text: colors[pIdx % colors.length],
            };
      const pad = 3;
      const innerBounds: TreemapRect = {
        x: pBox.x + pad,
        y: pBox.y + 24, // Reserve 24px header for project title
        w: Math.max(0, pBox.w - pad * 2),
        h: Math.max(0, pBox.h - 24 - pad),
      };

      const appBoxes =
        innerBounds.w > 10 && innerBounds.h > 10
          ? squarify(pBox.apps, innerBounds)
          : [];

      return {
        ...pBox,
        palette,
        appBoxes,
      };
    });
  }, [data, paletteId, colors]);

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-5">
        <div className="h-64 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div
      role="region"
      aria-label="Project Time Treemap"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-500/10 text-violet-400">
            <GridIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">
              Project Time Treemap
            </h3>
            <p className="text-xs text-ink-400">
              Hierarchical view of time spent across projects & applications
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            {([1, 7, 30] as const).map((days) => (
              <button
                key={days}
                onClick={() => setWindowDays(days)}
                className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                  windowDays === days
                    ? "bg-violet-500/20 font-medium text-violet-300"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                {days === 1 ? "Today" : `${days}d`}
              </button>
            ))}
          </div>

          <ChartPalettePicker variant="compact" />

          <ChartExportButton
            title={`project_treemap_${windowDays}d`}
            getSvg={() => svgRef.current}
          />
        </div>
      </div>

      {data.projects.length === 0 ? (
        <div className="py-12 text-center text-xs text-ink-400">
          No project activity recorded for this period.
        </div>
      ) : (
        <div className="mt-5 space-y-4">
          {/* Main SVG Treemap Canvas */}
          <div className="relative overflow-hidden rounded-xl border border-white/[0.08] bg-black/40 p-1.5">
            <svg
              ref={svgRef}
              viewBox="0 0 680 340"
              className="w-full h-auto overflow-hidden select-none"
              aria-hidden="true"
            >
              {layout.map((proj) => {
                const isHoveredProj = hoveredNode?.project === proj.name && !hoveredNode?.app;

                return (
                  <g key={proj.name}>
                    {/* Project Outer Container Box */}
                    <rect
                      x={proj.x + 1}
                      y={proj.y + 1}
                      width={Math.max(0, proj.w - 2)}
                      height={Math.max(0, proj.h - 2)}
                      fill={proj.palette.bg}
                      stroke={isHoveredProj ? proj.palette.border : "rgba(255,255,255,0.06)"}
                      strokeWidth={isHoveredProj ? 2 : 1}
                      rx="6"
                      className="cursor-pointer transition-colors"
                      onClick={() => onSelectProject?.(proj.name)}
                      onMouseEnter={() =>
                        setHoveredNode({
                          project: proj.name,
                          seconds: proj.seconds,
                          pct: proj.pct,
                        })
                      }
                      onMouseLeave={() => setHoveredNode(null)}
                    />

                    {/* Project Header Label (if space permits) */}
                    {proj.w > 60 && proj.h > 30 && (
                      <g
                        className="cursor-pointer"
                        onClick={() => onSelectProject?.(proj.name)}
                      >
                        <text
                          x={proj.x + 8}
                          y={proj.y + 16}
                          className="font-semibold text-[11px]"
                          fill={proj.palette.text}
                        >
                          {proj.name}
                        </text>
                        {proj.w > 120 && (
                          <text
                            x={proj.x + proj.w - 8}
                            y={proj.y + 16}
                            textAnchor="end"
                            className="font-mono text-[10px]"
                            fill="rgba(255,255,255,0.5)"
                          >
                            {fmtSecs(proj.seconds)} ({proj.pct}%)
                          </text>
                        )}
                      </g>
                    )}

                    {/* Nested Application Leaf Rectangles */}
                    {proj.appBoxes.map((app) => {
                      const isHoveredApp =
                        hoveredNode?.project === proj.name && hoveredNode?.app === app.name;

                      return (
                        <g key={`${proj.name}-${app.name}`}>
                          <rect
                            x={app.x + 1}
                            y={app.y + 1}
                            width={Math.max(0, app.w - 2)}
                            height={Math.max(0, app.h - 2)}
                            fill="rgba(0,0,0,0.35)"
                            stroke={isHoveredApp ? "#ffffff" : "rgba(255,255,255,0.12)"}
                            strokeWidth={isHoveredApp ? 1.5 : 0.75}
                            rx="4"
                            className="cursor-pointer transition-colors"
                            onMouseEnter={(e) => {
                              e.stopPropagation();
                              setHoveredNode({
                                project: proj.name,
                                app: app.name,
                                seconds: app.seconds,
                                pct: app.pct_of_project,
                              });
                            }}
                            onMouseLeave={() => setHoveredNode(null)}
                          />

                          {/* App text label if large enough */}
                          {app.w > 45 && app.h > 24 && (
                            <text
                              x={app.x + 6}
                              y={app.y + 15}
                              className="font-medium text-[10px] pointer-events-none"
                              fill="rgba(255,255,255,0.85)"
                            >
                              {app.name}
                            </text>
                          )}
                          {app.w > 60 && app.h > 38 && (
                            <text
                              x={app.x + 6}
                              y={app.y + 28}
                              className="font-mono text-[9px] pointer-events-none"
                              fill="rgba(255,255,255,0.45)"
                            >
                              {fmtSecs(app.seconds)}
                            </text>
                          )}
                        </g>
                      );
                    })}
                  </g>
                );
              })}
            </svg>

            {/* Hover Tooltip Overlay */}
            {hoveredNode && (
              <div className="absolute bottom-3 right-3 rounded-xl border border-white/10 bg-zinc-950/90 px-3.5 py-2 text-xs shadow-2xl backdrop-blur">
                <div className="flex items-center gap-2">
                  <FolderIcon className="h-3.5 w-3.5 text-violet-400" />
                  <span className="font-semibold text-ink-100">{hoveredNode.project}</span>
                  {hoveredNode.app && (
                    <>
                      <span className="text-ink-500">/</span>
                      <span className="font-medium text-sky-300">{hoveredNode.app}</span>
                    </>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-3 font-mono text-[11px] text-ink-300">
                  <span className="font-bold text-white">{fmtSecs(hoveredNode.seconds)}</span>
                  <span className="text-ink-400">({hoveredNode.pct}% of {hoveredNode.app ? "project" : "total"})</span>
                </div>
              </div>
            )}
          </div>

          {/* Quick Metrics & Top Projects Strip */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-xs">
            <div className="flex items-center gap-4">
              <span className="text-ink-400">
                Total tracked: <strong className="font-mono text-ink-200">{fmtSecs(data.total_seconds)}</strong>
              </span>
              <span className="text-ink-400">
                Active projects: <strong className="font-mono text-ink-200">{data.project_count}</strong>
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="text-[11px] text-ink-400">Top:</span>
              {data.projects.slice(0, 3).map((p, idx) => (
                <button
                  key={p.name}
                  onClick={() => onSelectProject?.(p.name)}
                  className="rounded-lg border border-white/[0.04] bg-white/[0.02] px-2 py-0.5 text-[11px] font-medium text-ink-300 hover:bg-white/[0.06] hover:text-white"
                >
                  <span
                    className="inline-block h-2 w-2 rounded-full mr-1.5"
                    style={{ backgroundColor: PROJECT_PALETTE[idx % PROJECT_PALETTE.length].border }}
                  />
                  {p.name} ({p.pct}%)
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
