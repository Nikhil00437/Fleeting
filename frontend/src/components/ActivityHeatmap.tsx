/**
 * #59 calendar heatmap of active minutes.
 *
 * One cell per day, GitHub-style: the colour ramp lives here so "how busy
 * looks" has a single home. Days with no tracking are drawn, not skipped —
 * a gap in the grid should read as a gap.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { HeatmapCell, HeatmapData } from "../types";

const WEEKDAY = ["Mon", "", "Wed", "", "Fri", "", "Sun"];

/** Five steps is enough to read at a glance; the ramp is linear in minutes. */
function step(minutes: number, peak: number): number {
  if (minutes <= 0) return 0;
  const ratio = minutes / Math.max(peak, 1);
  if (ratio > 0.75) return 5;
  if (ratio > 0.5) return 4;
  if (ratio > 0.25) return 3;
  if (ratio > 0.1) return 2;
  return 1;
}

const RAMP = [
  "bg-ink-900",
  "bg-ember-500/25",
  "bg-ember-500/45",
  "bg-ember-500/70",
  "bg-ember-400",
  "bg-ember-300",
];

/** Column-major layout: every column is a Monday-to-Sunday week. */
function weeksOf(grid: HeatmapData): Array<Array<HeatmapCell | null>> {
  const lead = (new Date(`${grid.from}T12:00:00`).getDay() + 6) % 7;
  const columns: Array<Array<HeatmapCell | null>> = [];
  const at = (i: number): Array<HeatmapCell | null> => (columns[i] ??= []);
  for (let i = 0; i < lead; i++) at(0).push(null);
  grid.cells.forEach((cell, idx) => {
    const slot = lead + idx;
    at(Math.floor(slot / 7)).push(cell);
    while (at(Math.floor(slot / 7)).length <= slot % 7) at(Math.floor(slot / 7)).push(null);
  });
  if (columns.length === 0) columns.push([]);
  while (columns[columns.length - 1].length < 7) columns[columns.length - 1].push(null);
  return columns;
}

export default function ActivityHeatmap({ onOpenDay }: { onOpenDay?: (day: string) => void }) {
  const [grid, setGrid] = useState<HeatmapData | null>(null);

  useEffect(() => {
    api.activityHeatmap(12).then(setGrid).catch(() => setGrid(null));
  }, []);

  const columns = useMemo(() => (grid ? weeksOf(grid) : []), [grid]);

  if (!grid) return null;

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Active minutes by day">
      <div className="mb-2 flex items-baseline justify-between">
        <p className="micro-label">Calendar — active minutes</p>
        <span className="font-mono text-[10px] text-ink-500">
          peak {Math.floor(grid.peak_minutes / 60)}h
        </span>
      </div>
      <div className="flex gap-1">
        <div className="flex flex-col justify-between pr-1 pt-0.5">
          {WEEKDAY.map((d, i) => (
            <span key={i} className="h-2.5 font-mono text-[8px] leading-none text-ink-600">
              {d}
            </span>
          ))}
        </div>
        <div className="flex gap-[3px] overflow-x-auto">
          {columns.map((week, wi) => (
            <div key={wi} className="flex flex-col gap-[3px]">
              {[0, 1, 2, 3, 4, 5, 6].map((dow) => {
                const cell = week[dow] ?? null;
                if (!cell) return <span key={dow} className="h-2.5 w-2.5" />;
                return (
                  <button
                    key={cell.day}
                    onClick={onOpenDay ? () => onOpenDay(cell.day) : undefined}
                    title={`${cell.day}: ${cell.minutes} min`}
                    aria-label={`${cell.day}: ${cell.minutes} minutes`}
                    className={`h-2.5 w-2.5 rounded-[2px] ${RAMP[step(cell.minutes, grid.peak_minutes)]}`}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}