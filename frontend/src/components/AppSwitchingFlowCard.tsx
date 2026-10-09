import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { appColor, prettyAppName } from "../apps";
import { ActivityIcon, ChevronLeftIcon, ChevronRightIcon } from "./Icons";
import ChartExportButton from "./ChartExportButton";
import ChartPalettePicker from "./ChartPalettePicker";
import { useChartPalette } from "../chartPalettes";
import type { AppFlowData, AppFlowLink } from "../types";

interface Props {
  refreshKey: number;
  initialDay?: string;
  onSelectApp?: (app: string) => void;
}

function shiftDay(dayStr: string, deltaDays: number): string {
  const [y, m, d] = dayStr.split("-").map(Number);
  const dt = new Date(y, m - 1, d + deltaDays);
  const yyyy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export default function AppSwitchingFlowCard({
  refreshKey,
  initialDay,
  onSelectApp,
}: Props) {
  const [windowDays, setWindowDays] = useState<1 | 7 | 30>(7);
  const [day, setDay] = useState<string>(
    initialDay || new Date().toISOString().slice(0, 10)
  );
  const [data, setData] = useState<AppFlowData | null>(null);
  const [loading, setLoading] = useState(true);
  const [hoveredLink, setHoveredLink] = useState<AppFlowLink | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const { paletteId } = useChartPalette();
  const svgRef = useRef<SVGSVGElement>(null);
  const baseGradId = useId();

  useEffect(() => {
    if (initialDay && initialDay !== day) {
      setDay(initialDay);
    }
  }, [initialDay]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .activityFlow({ day, days: windowDays, top_n: 10 })
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
  }, [day, windowDays, refreshKey]);

  // Layout Computation for Flow / Sankey Ribbon Geometry
  const layout = useMemo(() => {
    if (!data || data.links.length === 0 || data.total_switches === 0) return null;

    const width = 680;
    const height = 300;
    const nodeWidth = 120;
    const paddingX = 24;
    const paddingY = 24;
    const availableHeight = height - paddingY * 2;

    const leftX = paddingX;
    const rightX = width - paddingX - nodeWidth;

    // Filter nodes with actual outgoing / incoming
    const sourceAppIds = Array.from(new Set(data.links.map((l) => l.source)));
    const targetAppIds = Array.from(new Set(data.links.map((l) => l.target)));

    // Total outgoing across sources
    const totalOut = data.links.reduce((s, l) => s + l.value, 0);
    const gap = 8;

    // Layout left source nodes
    let curY = paddingY;
    const sourceNodeBoxes = new Map<
      string,
      { x: number; y: number; w: number; h: number; app: string; val: number }
    >();

    const totalSourceGaps = Math.max(0, sourceAppIds.length - 1) * gap;
    const usableSourceHeight = Math.max(10, availableHeight - totalSourceGaps);

    sourceAppIds.forEach((appId) => {
      const appOut = data.links
        .filter((l) => l.source === appId)
        .reduce((s, l) => s + l.value, 0);
      const h = Math.max(18, (appOut / totalOut) * usableSourceHeight);
      sourceNodeBoxes.set(appId, {
        x: leftX,
        y: curY,
        w: nodeWidth,
        h,
        app: appId,
        val: appOut,
      });
      curY += h + gap;
    });

    // Layout right target nodes
    curY = paddingY;
    const targetNodeBoxes = new Map<
      string,
      { x: number; y: number; w: number; h: number; app: string; val: number }
    >();

    const totalTargetGaps = Math.max(0, targetAppIds.length - 1) * gap;
    const usableTargetHeight = Math.max(10, availableHeight - totalTargetGaps);

    targetAppIds.forEach((appId) => {
      const appIn = data.links
        .filter((l) => l.target === appId)
        .reduce((s, l) => s + l.value, 0);
      const h = Math.max(18, (appIn / totalOut) * usableTargetHeight);
      targetNodeBoxes.set(appId, {
        x: rightX,
        y: curY,
        w: nodeWidth,
        h,
        app: appId,
        val: appIn,
      });
      curY += h + gap;
    });

    // Track vertical offsets within each node for stacking ribbons
    const sourceOffsets = new Map<string, number>();
    const targetOffsets = new Map<string, number>();

    const ribbons = data.links.map((l, linkIdx) => {
      const sBox = sourceNodeBoxes.get(l.source);
      const tBox = targetNodeBoxes.get(l.target);

      if (!sBox || !tBox) return null;

      const sOffset = sourceOffsets.get(l.source) || 0;
      const tOffset = targetOffsets.get(l.target) || 0;

      const ribbonHeightSrc = (l.value / sBox.val) * sBox.h;
      const ribbonHeightTgt = (l.value / tBox.val) * tBox.h;

      sourceOffsets.set(l.source, sOffset + ribbonHeightSrc);
      targetOffsets.set(l.target, tOffset + ribbonHeightTgt);

      const x0 = sBox.x + sBox.w;
      const y0_top = sBox.y + sOffset;
      const y0_bot = y0_top + ribbonHeightSrc;

      const x1 = tBox.x;
      const y1_top = tBox.y + tOffset;
      const y1_bot = y1_top + ribbonHeightTgt;

      const dx = (x1 - x0) * 0.5;

      const pathD = [
        `M ${x0.toFixed(1)} ${y0_top.toFixed(1)}`,
        `C ${(x0 + dx).toFixed(1)} ${y0_top.toFixed(1)}, ${(x1 - dx).toFixed(1)} ${y1_top.toFixed(1)}, ${x1.toFixed(1)} ${y1_top.toFixed(1)}`,
        `L ${x1.toFixed(1)} ${y1_bot.toFixed(1)}`,
        `C ${(x1 - dx).toFixed(1)} ${y1_bot.toFixed(1)}, ${(x0 + dx).toFixed(1)} ${y0_bot.toFixed(1)}, ${x0.toFixed(1)} ${y0_bot.toFixed(1)}`,
        "Z",
      ].join(" ");

      const srcColor = appColor(l.source);
      const tgtColor = appColor(l.target);

      return {
        link: l,
        idx: linkIdx,
        pathD,
        srcColor,
        tgtColor,
        midX: (x0 + x1) / 2,
        midY: (y0_top + y1_top) / 2,
      };
    }).filter(Boolean) as {
      link: AppFlowLink;
      idx: number;
      pathD: string;
      srcColor: string;
      tgtColor: string;
      midX: number;
      midY: number;
    }[];

    return {
      width,
      height,
      sourceNodes: Array.from(sourceNodeBoxes.values()),
      targetNodes: Array.from(targetNodeBoxes.values()),
      ribbons,
    };
  }, [data, paletteId]);

  if (loading) {
    return (
      <div className="glass-studio rounded-2xl border border-white/[0.06] p-5">
        <div className="h-64 animate-pulse rounded-xl bg-white/[0.02]" />
      </div>
    );
  }

  if (!data) return null;

  const topOrigin = data.nodes[0] ?? null;
  const topTarget =
    [...data.nodes].sort((a, b) => b.incoming - a.incoming)[0] ?? null;
  const topLoop = data.top_loops[0] ?? null;

  return (
    <div
      role="region"
      aria-label="App Switching Flow Chart"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500/10 text-sky-400">
            <ActivityIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">
              App Switching Flow
            </h3>
            <p className="text-xs text-ink-400">
              Directional transitions & context-switching loops between applications
            </p>
          </div>
        </div>

        {/* Header Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Day Navigator */}
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            <button
              onClick={() => setDay(shiftDay(day, -1))}
              aria-label="Previous day"
              className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
            >
              <ChevronLeftIcon className="h-4 w-4" />
            </button>
            <span className="px-1.5 font-mono text-xs text-ink-200">{day}</span>
            <button
              onClick={() => setDay(shiftDay(day, 1))}
              aria-label="Next day"
              className="rounded-lg p-1 text-ink-400 hover:bg-white/[0.05] hover:text-ink-200"
            >
              <ChevronRightIcon className="h-4 w-4" />
            </button>
          </div>

          {/* Window Range */}
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            {([1, 7, 30] as const).map((days) => (
              <button
                key={days}
                onClick={() => setWindowDays(days)}
                className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                  windowDays === days
                    ? "bg-sky-500/20 font-medium text-sky-300"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                {days === 1 ? "1d" : `${days}d`}
              </button>
            ))}
          </div>

          <ChartPalettePicker variant="compact" />

          <ChartExportButton
            title={`app_switching_flow_${day}_${windowDays}d`}
            getSvg={() => svgRef.current}
          />
        </div>
      </div>

      {/* KPI Deck */}
      <div className="mt-4 grid grid-cols-1 gap-2.5 sm:grid-cols-4">
        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Total Switches</div>
          <div className="mt-1 font-mono text-xl font-bold text-sky-400">
            {data.total_switches}
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Top Origin</div>
          <div className="mt-1 truncate font-mono text-sm font-semibold text-ink-200">
            {topOrigin ? prettyAppName(topOrigin.id) : "—"}
            {topOrigin && (
              <span className="ml-1 text-xs text-ink-400">({topOrigin.outgoing})</span>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Top Destination</div>
          <div className="mt-1 truncate font-mono text-sm font-semibold text-ink-200">
            {topTarget ? prettyAppName(topTarget.id) : "—"}
            {topTarget && (
              <span className="ml-1 text-xs text-ink-400">({topTarget.incoming})</span>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.04] bg-white/[0.02] p-3">
          <div className="text-[11px] font-medium text-ink-400">Main Switch Loop</div>
          <div className="mt-1 truncate font-mono text-xs font-semibold text-amber-400">
            {topLoop
              ? `${prettyAppName(topLoop.app_a)} ⇄ ${prettyAppName(topLoop.app_b)} (${topLoop.count})`
              : "—"}
          </div>
        </div>
      </div>

      {/* Visual Sankey / Flow Diagram */}
      {data.total_switches === 0 || !layout ? (
        <div className="py-12 text-center text-xs text-ink-400">
          No app transitions recorded for this period.
        </div>
      ) : (
        <div className="mt-5 space-y-3">
          {/* Column Titles */}
          <div className="flex items-center justify-between text-[11px] font-mono uppercase tracking-wider text-ink-400 px-6">
            <span>Origin Application</span>
            <span>Target Application</span>
          </div>

          <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-black/40 p-2">
            <svg
              ref={svgRef}
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              className="w-full h-auto overflow-visible select-none"
              aria-hidden="true"
            >
              <defs>
                {layout.ribbons.map((r) => (
                  <linearGradient
                    key={`grad-${r.idx}`}
                    id={`${baseGradId}-grad-${r.idx}`}
                    x1="0"
                    y1="0"
                    x2="1"
                    y2="0"
                  >
                    <stop offset="0%" stopColor={r.srcColor} stopOpacity="0.55" />
                    <stop offset="100%" stopColor={r.tgtColor} stopOpacity="0.55" />
                  </linearGradient>
                ))}
              </defs>

              {/* Transition Ribbons */}
              {layout.ribbons.map((r) => {
                const isHovered =
                  hoveredLink?.source === r.link.source &&
                  hoveredLink?.target === r.link.target;
                const isConnected =
                  hoveredNode &&
                  (hoveredNode === r.link.source || hoveredNode === r.link.target);

                const isDimmed =
                  (hoveredLink && !isHovered) || (hoveredNode && !isConnected);

                return (
                  <path
                    key={`ribbon-${r.idx}`}
                    d={r.pathD}
                    fill={`url(#${baseGradId}-grad-${r.idx})`}
                    stroke={isHovered ? "#ffffff" : "transparent"}
                    strokeWidth={isHovered ? 1.5 : 0}
                    opacity={isDimmed ? 0.12 : isHovered || isConnected ? 0.9 : 0.6}
                    className="cursor-pointer transition-opacity duration-200"
                    onMouseEnter={() => setHoveredLink(r.link)}
                    onMouseLeave={() => setHoveredLink(null)}
                  />
                );
              })}

              {/* Source Nodes (Left) */}
              {layout.sourceNodes.map((n) => {
                const isHovered = hoveredNode === n.app;
                const color = appColor(n.app);

                return (
                  <g
                    key={`src-${n.app}`}
                    className="cursor-pointer"
                    onClick={() => onSelectApp?.(n.app)}
                    onMouseEnter={() => setHoveredNode(n.app)}
                    onMouseLeave={() => setHoveredNode(null)}
                  >
                    <rect
                      x={n.x}
                      y={n.y}
                      width={n.w}
                      height={n.h}
                      rx="4"
                      fill="rgba(255,255,255,0.06)"
                      stroke={isHovered ? "#ffffff" : color}
                      strokeWidth={isHovered ? 2 : 1}
                    />
                    <text
                      x={n.x + 8}
                      y={n.y + Math.min(n.h / 2 + 4, 14)}
                      className="text-[10.5px] font-medium"
                      fill="#e2e8f0"
                    >
                      {prettyAppName(n.app)}
                    </text>
                    <text
                      x={n.x + n.w - 8}
                      y={n.y + Math.min(n.h / 2 + 4, 14)}
                      textAnchor="end"
                      className="font-mono text-[9.5px]"
                      fill="rgba(255,255,255,0.5)"
                    >
                      {n.val}
                    </text>
                  </g>
                );
              })}

              {/* Target Nodes (Right) */}
              {layout.targetNodes.map((n) => {
                const isHovered = hoveredNode === n.app;
                const color = appColor(n.app);

                return (
                  <g
                    key={`tgt-${n.app}`}
                    className="cursor-pointer"
                    onClick={() => onSelectApp?.(n.app)}
                    onMouseEnter={() => setHoveredNode(n.app)}
                    onMouseLeave={() => setHoveredNode(null)}
                  >
                    <rect
                      x={n.x}
                      y={n.y}
                      width={n.w}
                      height={n.h}
                      rx="4"
                      fill="rgba(255,255,255,0.06)"
                      stroke={isHovered ? "#ffffff" : color}
                      strokeWidth={isHovered ? 2 : 1}
                    />
                    <text
                      x={n.x + 8}
                      y={n.y + Math.min(n.h / 2 + 4, 14)}
                      className="text-[10.5px] font-medium"
                      fill="#e2e8f0"
                    >
                      {prettyAppName(n.app)}
                    </text>
                    <text
                      x={n.x + n.w - 8}
                      y={n.y + Math.min(n.h / 2 + 4, 14)}
                      textAnchor="end"
                      className="font-mono text-[9.5px]"
                      fill="rgba(255,255,255,0.5)"
                    >
                      {n.val}
                    </text>
                  </g>
                );
              })}
            </svg>

            {/* Hover Tooltip Popover */}
            {hoveredLink && (
              <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-xl border border-white/10 bg-zinc-950/95 px-3 py-1.5 text-xs shadow-2xl backdrop-blur">
                <span className="font-semibold text-sky-300">
                  {prettyAppName(hoveredLink.source)}
                </span>
                <span className="text-ink-400 mx-1.5">→</span>
                <span className="font-semibold text-emerald-300">
                  {prettyAppName(hoveredLink.target)}
                </span>
                <span className="ml-2 font-mono text-ink-200">
                  : {hoveredLink.value} switches ({hoveredLink.pct}%)
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
