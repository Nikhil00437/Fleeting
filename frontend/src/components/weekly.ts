/** Presentation helpers for the weekly digest.
 *
 * The backend already does the week arithmetic (Monday-based, range validated);
 * this only formats what it returns and derives the few numbers the chart needs.
 */

export interface WeekDay {
  day: string;
  seconds: number;
  busy: boolean;
}

export interface WeekProgress {
  totalSeconds: number;
  busyDays: number;
  busiest: string | null;
  /** Mean across all seven days, so a one-day week still reads honestly. */
  averageSeconds: number;
}

/**
 * Format a Date as YYYY-MM-DD using *local* components.
 *
 * Not `toISOString()`: that converts to UTC, so local midnight on a Monday
 * becomes Sunday east of Greenwich and the week label reads a day early.
 */
function localISO(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

/** "Week of 2026-10-05 → 2026-10-11", degrading gracefully on bad input. */
export function weekLabel(weekStart: string): string {
  const start = new Date(`${weekStart}T00:00:00`);
  if (Number.isNaN(start.getTime())) return `Week of ${weekStart}`;
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return `Week of ${localISO(start)} → ${localISO(end)}`;
}

function seconds(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0;
}

export function weekProgress(days: WeekDay[] | null | undefined): WeekProgress {
  const rows = Array.isArray(days) ? days : [];
  const clean = rows.map((d) => ({
    day: typeof d?.day === "string" ? d.day : "",
    seconds: seconds(d?.seconds),
  }));

  const totalSeconds = clean.reduce((sum, d) => sum + d.seconds, 0);
  const busiestRow = clean.reduce<WeekDay | null>(
    (best, d) => (d.seconds > 0 && (!best || d.seconds > best.seconds) ? { ...d, busy: true } : best),
    null,
  );

  return {
    totalSeconds,
    // "Busy" means the backend already decided the day cleared its threshold.
    busyDays: rows.filter((d) => d?.busy === true).length,
    busiest: busiestRow?.day || null,
    averageSeconds: clean.length ? Math.round(totalSeconds / clean.length) : 0,
  };
}
