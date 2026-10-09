import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { SparkIcon } from "./Icons";
import type { TagGraphData } from "../types";

const TAG_COLORS = [
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
  onSelectTag?: (tag: string, coTag?: string) => void;
}

export default function TagAnalyticsCard({ refreshKey, onSelectTag }: Props) {
  const [mode, setMode] = useState<"matrix" | "stream">("matrix");
  const [topN, setTopN] = useState<6 | 8 | 12>(8);
  const [weeks, setWeeks] = useState<4 | 8 | 12>(8);
  const [data, setData] = useState<TagGraphData | null>(null);
  const [loading, setLoading] = useState(true);

  // Matrix hover state
  const [hoveredCell, setHoveredCell] = useState<{ row: number; col: number } | null>(null);
  // Stream hover state
  const [hoveredStreamTag, setHoveredStreamTag] = useState<string | null>(null);
  const [hoveredWeekIdx, setHoveredWeekIdx] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .tagGraph({ top_n: topN, weeks })
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
  }, [topN, weeks, refreshKey]);

  // Color mapping per tag
  const colorMap = useMemo(() => {
    const map = new Map<string, string>();
    if (!data) return map;
    data.top_tags.forEach((t, idx) => {
      map.set(t.tag, TAG_COLORS[idx % TAG_COLORS.length]);
    });
    return map;
  }, [data]);

  // Max value in matrix (excluding diagonal) for opacity scaling
  const maxCooccur = useMemo(() => {
    if (!data || data.matrix.length === 0) return 1;
    let maxV = 1;
    for (let i = 0; i < data.matrix.length; i++) {
      for (let j = 0; j < data.matrix.length; j++) {
        if (i !== j && data.matrix[i][j] > maxV) {
          maxV = data.matrix[i][j];
        }
      }
    }
    return maxV;
  }, [data]);

  // Stream Stack Computation Geometry
  const streamLayout = useMemo(() => {
    if (!data || data.stream.length === 0 || data.weeks.length === 0) return null;
    const wCount = data.weeks.length;
    const width = 640;
    const height = 200;
    const paddingX = 36;
    const paddingY = 20;
    const usableW = width - paddingX * 2;
    const usableH = height - paddingY * 2;

    // Calculate weekly sums across all tags
    const weeklyTotals = Array(wCount).fill(0);
    for (let w = 0; w < wCount; w++) {
      for (const s of data.stream) {
        weeklyTotals[w] += s.counts[w] || 0;
      }
    }
    const maxWeeklyTotal = Math.max(1, ...weeklyTotals);

    // Baseline stack calculation
    const baselines: number[][] = []; // baselines[w][layerIdx]
    for (let w = 0; w < wCount; w++) {
      baselines[w] = [0];
      let acc = 0;
      for (let i = 0; i < data.stream.length; i++) {
        acc += data.stream[i].counts[w] || 0;
        baselines[w].push(acc);
      }
    }

    // Build SVG polygon / area paths for each tag ribbon
    const ribbons = data.stream.map((s, idx) => {
      const topPoints: { x: number; y: number }[] = [];
      const bottomPoints: { x: number; y: number }[] = [];

      for (let w = 0; w < wCount; w++) {
        const x = paddingX + (w / (wCount - 1)) * usableW;
        const bBottom = baselines[w][idx];
        const bTop = baselines[w][idx + 1];

        const yBottom = height - paddingY - (bBottom / maxWeeklyTotal) * usableH;
        const yTop = height - paddingY - (bTop / maxWeeklyTotal) * usableH;

        topPoints.push({ x, y: yTop });
        bottomPoints.push({ x, y: yBottom });
      }

      // Compose SVG path: left to right along top, right to left along bottom
      const pathD = [
        `M ${topPoints[0].x.toFixed(1)} ${topPoints[0].y.toFixed(1)}`,
        ...topPoints.slice(1).map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`),
        ...bottomPoints.reverse().map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`),
        "Z",
      ].join(" ");

      return {
        tag: s.tag,
        color: colorMap.get(s.tag) || "#38bdf8",
        pathD,
        total: s.total_in_window,
      };
    });

    return {
      width,
      height,
      paddingX,
      paddingY,
      usableW,
      usableH,
      maxWeeklyTotal,
      ribbons,
    };
  }, [data, colorMap]);

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
      aria-label="Tag Co-occurrence & Topic Stream"
      className="glass-studio rounded-2xl border border-white/[0.06] p-5 shadow-xl"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] pb-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
            <SparkIcon className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-wide text-ink-100">
              Tag Co-occurrence & Topic Stream
            </h3>
            <p className="text-xs text-ink-400">
              Knowledge clustering & topic trends over time ({data.total_tagged_notes} notes)
            </p>
          </div>
        </div>

        {/* View Toggle & Filter Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Mode toggle */}
          <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
            <button
              onClick={() => setMode("matrix")}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                mode === "matrix"
                  ? "bg-emerald-500/20 font-medium text-emerald-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              Co-occurrence Matrix
            </button>
            <button
              onClick={() => setMode("stream")}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                mode === "stream"
                  ? "bg-emerald-500/20 font-medium text-emerald-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              Topic Stream
            </button>
          </div>

          {/* Sub-filter */}
          {mode === "matrix" ? (
            <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
              {([6, 8, 12] as const).map((cnt) => (
                <button
                  key={cnt}
                  onClick={() => setTopN(cnt)}
                  className={`rounded-lg px-2 py-0.5 font-mono text-xs transition-colors ${
                    topN === cnt
                      ? "bg-white/[0.08] font-semibold text-ink-100"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  Top {cnt}
                </button>
              ))}
            </div>
          ) : (
            <div className="flex items-center gap-1 rounded-xl bg-black/20 p-1">
              {([4, 8, 12] as const).map((w) => (
                <button
                  key={w}
                  onClick={() => setWeeks(w)}
                  className={`rounded-lg px-2 py-0.5 font-mono text-xs transition-colors ${
                    weeks === w
                      ? "bg-white/[0.08] font-semibold text-ink-100"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {w}w
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {data.top_tags.length === 0 ? (
        <div className="py-12 text-center text-xs text-ink-400">
          No tagged notes available to generate co-occurrence or stream charts.
        </div>
      ) : mode === "matrix" ? (
        /* View 1: Co-occurrence Matrix Heatmap */
        <div className="mt-5 space-y-4">
          <div className="overflow-x-auto pb-2">
            <table className="w-full border-collapse text-xs select-none">
              <thead>
                <tr>
                  <th className="p-1 text-left font-mono text-[10px] text-ink-500 font-normal">
                    tag \ co-tag
                  </th>
                  {data.top_tags.map((t, cIdx) => (
                    <th
                      key={t.tag}
                      onClick={() => onSelectTag?.(t.tag)}
                      title={`Filter notes with #${t.tag}`}
                      className={`p-1.5 text-center font-mono text-[10px] font-semibold transition-colors cursor-pointer hover:underline ${
                        hoveredCell?.col === cIdx ? "text-emerald-300" : "text-ink-300"
                      }`}
                    >
                      #{t.tag}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.top_tags.map((rowTag, rIdx) => (
                  <tr key={rowTag.tag} className="border-t border-white/[0.02]">
                    <td
                      onClick={() => onSelectTag?.(rowTag.tag)}
                      title={`Filter notes with #${rowTag.tag}`}
                      className={`py-1.5 pr-2 font-mono text-[10px] font-semibold whitespace-nowrap transition-colors cursor-pointer hover:underline ${
                        hoveredCell?.row === rIdx ? "text-emerald-300" : "text-ink-300"
                      }`}
                    >
                      #{rowTag.tag}
                    </td>

                    {data.top_tags.map((colTag, cIdx) => {
                      const count = data.matrix[rIdx][cIdx];
                      const isDiag = rIdx === cIdx;
                      const isHovered =
                        hoveredCell?.row === rIdx && hoveredCell?.col === cIdx;
                      const isInHoverCross =
                        hoveredCell?.row === rIdx || hoveredCell?.col === cIdx;

                      // Opacity calculation for heatmap
                      const opacity = isDiag
                        ? 0.08
                        : count > 0
                        ? 0.15 + (count / maxCooccur) * 0.7
                        : 0.02;

                      const bgColor = isDiag
                        ? "rgba(255, 255, 255, 0.08)"
                        : count > 0
                        ? `rgba(16, 185, 129, ${opacity.toFixed(2)})`
                        : "transparent";

                      return (
                        <td
                          key={colTag.tag}
                          onClick={() =>
                            isDiag
                              ? onSelectTag?.(rowTag.tag)
                              : onSelectTag?.(rowTag.tag, colTag.tag)
                          }
                          title={
                            isDiag
                              ? `Filter notes with #${rowTag.tag}`
                              : `Filter notes with both #${rowTag.tag} and #${colTag.tag} (${count})`
                          }
                          onMouseEnter={() => setHoveredCell({ row: rIdx, col: cIdx })}
                          onMouseLeave={() => setHoveredCell(null)}
                          className={`p-1 text-center font-mono text-[11px] transition-all cursor-pointer ${
                            isHovered
                              ? "ring-1 ring-emerald-400 font-bold text-white scale-105"
                              : isInHoverCross
                              ? "brightness-125"
                              : ""
                          }`}
                        >
                          <div
                            style={{ backgroundColor: bgColor }}
                            className={`flex h-8 min-w-[34px] items-center justify-center rounded-md ${
                              isDiag
                                ? "text-ink-400 font-medium"
                                : count > 0
                                ? "text-emerald-100 font-semibold"
                                : "text-ink-600"
                            }`}
                          >
                            {count > 0 ? count : "·"}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Matrix Hover Details / Explainer Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.04] bg-white/[0.02] p-3 text-xs">
            {hoveredCell ? (
              <div className="flex items-center gap-2">
                <span className="font-semibold text-emerald-400 font-mono">
                  #{data.top_tags[hoveredCell.row].tag}
                </span>
                <span className="text-ink-400">+</span>
                <span className="font-semibold text-emerald-400 font-mono">
                  #{data.top_tags[hoveredCell.col].tag}
                </span>
                <span className="text-ink-300">
                  {hoveredCell.row === hoveredCell.col
                    ? `appear on ${data.matrix[hoveredCell.row][hoveredCell.col]} notes in total`
                    : `co-occur on ${data.matrix[hoveredCell.row][hoveredCell.col]} notes together`}
                </span>
              </div>
            ) : (
              <div className="text-ink-400">
                Hover over matrix cells to inspect pairwise co-occurrence frequencies.
              </div>
            )}

            {/* Top Pairs pills */}
            <div className="flex items-center gap-1.5 overflow-x-auto text-[11px]">
              <span className="text-ink-500 font-medium mr-1">Strongest:</span>
              {data.pairs.slice(0, 3).map((p) => (
                <span
                  key={`${p.tag_a}-${p.tag_b}`}
                  className="rounded-lg bg-emerald-500/10 px-2 py-0.5 font-mono text-emerald-300"
                >
                  #{p.tag_a} & #{p.tag_b} ({p.count})
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* View 2: Topic-Over-Time Stream Chart */
        <div className="mt-5 space-y-4">
          {streamLayout && (
            <div className="relative overflow-hidden rounded-xl border border-white/[0.04] bg-black/40 p-2">
              <svg
                viewBox={`0 0 ${streamLayout.width} ${streamLayout.height}`}
                className="w-full h-auto overflow-visible select-none"
                aria-hidden="true"
              >
                {/* Horizontal Guide lines */}
                {[0, 0.5, 1].map((r) => {
                  const y =
                    streamLayout.height -
                    streamLayout.paddingY -
                    r * streamLayout.usableH;
                  return (
                    <line
                      key={r}
                      x1={streamLayout.paddingX}
                      y1={y}
                      x2={streamLayout.width - streamLayout.paddingX}
                      y2={y}
                      stroke="rgba(255,255,255,0.06)"
                      strokeDasharray="3 3"
                    />
                  );
                })}

                {/* Stream ribbons */}
                {streamLayout.ribbons.map((ribbon) => {
                  const isHovered = hoveredStreamTag === ribbon.tag;

                  return (
                    <path
                      key={ribbon.tag}
                      d={ribbon.pathD}
                      fill={ribbon.color}
                      fillOpacity={isHovered ? 0.9 : 0.6}
                      stroke={isHovered ? "#ffffff" : "rgba(0,0,0,0.3)"}
                      strokeWidth={isHovered ? 1.5 : 0.5}
                      className="cursor-pointer transition-all duration-150"
                      onClick={() => onSelectTag?.(ribbon.tag)}
                      onMouseEnter={() => setHoveredStreamTag(ribbon.tag)}
                      onMouseLeave={() => setHoveredStreamTag(null)}
                    />
                  );
                })}

                {/* Vertical time ticks */}
                {data.weeks.map((wStr, wIdx) => {
                  const x =
                    streamLayout.paddingX +
                    (wIdx / (data.weeks.length - 1)) * streamLayout.usableW;
                  const isHovered = hoveredWeekIdx === wIdx;

                  return (
                    <g key={wStr}>
                      <line
                        x1={x}
                        y1={streamLayout.height - streamLayout.paddingY}
                        x2={x}
                        y2={streamLayout.height - streamLayout.paddingY + 4}
                        stroke={isHovered ? "#ffffff" : "rgba(255,255,255,0.2)"}
                      />
                      <text
                        x={x}
                        y={streamLayout.height - 4}
                        textAnchor="middle"
                        className="fill-ink-400 font-mono text-[9px]"
                      >
                        {wStr.slice(5)}
                      </text>
                      {/* Invisible hover trigger */}
                      <rect
                        x={x - streamLayout.usableW / (data.weeks.length * 2)}
                        y={0}
                        width={streamLayout.usableW / data.weeks.length}
                        height={streamLayout.height}
                        fill="transparent"
                        onMouseEnter={() => setHoveredWeekIdx(wIdx)}
                        onMouseLeave={() => setHoveredWeekIdx(null)}
                      />
                    </g>
                  );
                })}
              </svg>

              {/* Tooltip on stream hover */}
              {hoveredStreamTag && (
                <div className="absolute top-3 right-3 rounded-xl border border-white/10 bg-zinc-950/90 px-3 py-1.5 font-mono text-xs shadow-xl backdrop-blur">
                  <span className="font-semibold text-white">#{hoveredStreamTag}</span>
                  <span className="text-ink-400 ml-2">
                    {data.stream.find((s) => s.tag === hoveredStreamTag)?.total_in_window} notes
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Stream Legend */}
          <div className="flex flex-wrap items-center gap-3 pt-1 text-xs">
            {data.stream.map((s) => {
              const color = colorMap.get(s.tag) || "#38bdf8";
              const isHovered = hoveredStreamTag === s.tag;

              return (
                <button
                  key={s.tag}
                  onMouseEnter={() => setHoveredStreamTag(s.tag)}
                  onMouseLeave={() => setHoveredStreamTag(null)}
                  className={`flex items-center gap-1.5 rounded-lg px-2 py-1 font-mono text-xs transition-colors ${
                    isHovered
                      ? "bg-white/[0.08] text-white"
                      : "text-ink-300 hover:text-white"
                  }`}
                >
                  <span
                    className="h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: color }}
                  />
                  <span>#{s.tag}</span>
                  <span className="text-ink-500 font-normal">({s.total_in_window})</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
