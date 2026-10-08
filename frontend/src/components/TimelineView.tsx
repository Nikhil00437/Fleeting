import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import ActivityHeatmap from "./ActivityHeatmap";
import FocusMetrics from "./FocusMetrics";
import GapCard from "./GapCard";
import PrivateBadge from "./PrivateBadge";
import RangeAsk from "./RangeAsk";
import SessionEditor from "./SessionEditor";
import { appColor, appMonogram, fmtSecs, prettyAppName } from "../apps";
import { AreaTrend, Bars, Donut, SessionRibbon } from "./charts";
import {
  ActivityIcon,
  CalendarIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ClockIcon,
  FileIcon,
  FilterIcon,
  FolderIcon,
  GitCommitIcon,
  PauseIcon,
  PlayIcon,
  SearchIcon,
  XIcon,
} from "./Icons";
import type { ActivityGap, ActivityDay, ActivitySession, DayEvent, FilesActivity } from "../types";

function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftDay(day: string, delta: number): string {
  const d = new Date(day + "T12:00:00");
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function prettyDay(day: string): string {
  if (day === todayLocal()) return "Today";
  const d = new Date(day + "T12:00:00");
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

const hhmm = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** Distribute session seconds across the local hours they actively span (ignoring idle sleep gaps). */
function hourly(
  sessions: ActivitySession[],
): { key: string; label: string; value: number; hint: string }[] {
  const buckets = Array.from({ length: 24 }, (_, h) => ({
    key: String(h),
    label: `${String(h).padStart(2, "0")}`,
    value: 0,
    hint: "",
  }));
  for (const s of sessions) {
    const start = new Date(s.first_seen).getTime();
    const rawEnd = new Date(s.last_seen).getTime();
    const wallMs = Math.max(0, rawEnd - start);
    const activeMs = Math.max(s.seconds * 1000, 1000);
    // If wall-clock span is much larger than active time (idle/suspend gap), anchor to first_seen + activeMs
    const end = wallMs > activeMs * 2.2 ? start + activeMs : Math.max(rawEnd, start + activeMs);
    const span = Math.max(end - start, activeMs, 1000);
    let remaining = s.seconds;
    const cur = new Date(start);
    for (let guard = 0; guard < 6 && remaining > 0; guard++) {
      const h = cur.getHours();
      const nextHour = new Date(cur);
      nextHour.setMinutes(0, 0, 0);
      nextHour.setHours(cur.getHours() + 1);
      const sliceMs = Math.min(nextHour.getTime() - cur.getTime(), span, remaining * 1000);
      buckets[h].value += Math.round((sliceMs / 1000) * (s.seconds / (span / 1000)) || 0);
      remaining -= Math.round(sliceMs / 1000);
      cur.setTime(nextHour.getTime());
    }
  }
  for (const b of buckets) {
    b.hint = `${b.label}:00 — ${fmtSecs(b.value)}`;
  }
  return buckets;
}

const shortDayLabel = (day: string, totalDays: number) => {
  const d = new Date(day + "T12:00:00");
  if (totalDays <= 7) return d.toLocaleDateString([], { weekday: "short" });
  return `${d.getMonth() + 1}/${d.getDate()}`;
};

interface Props {
  onToast: (message: string, kind?: "ok" | "err") => void;
  refreshKey: number;
  /** #339 clicking a note marker opens that note. */
  onOpenNote?: (id: string) => void;
  /** #342 base URL for downloads; prefixed with the API origin by the caller. */
  exportBase?: string;
}

export default function TimelineView({ onToast, refreshKey, onOpenNote }: Props) {
  const [day, setDay] = useState(todayLocal());
  const [data, setData] = useState<ActivityDay | null>(null);
  const [live, setLive] = useState<ActivitySession | null>(null);
  const [files, setFiles] = useState<FilesActivity | null>(null);
  const [filesLoading, setFilesLoading] = useState(true);
  const [filesHours, setFilesHours] = useState<number>(24);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  // Trend chart controls
  const [rangeDays, setRangeDays] = useState<7 | 14 | 30>(7);
  const [trendMode, setTrendMode] = useState<"bars" | "area">("bars");
  const [week, setWeek] = useState<{ day: string; seconds: number }[]>([]);
  // #339 note/task markers for the ribbon.
  const [events, setEvents] = useState<DayEvent[]>([]);
  // #337 untracked stretches for the shown day.
  const [gaps, setGaps] = useState<ActivityGap[]>([]);
  // #53 time per project for the shown day.
  const [projects, setProjects] = useState<{ project: string | null; seconds: number }[]>([]);

  // Interactive cross-filters
  const [selectedApp, setSelectedApp] = useState<string | null>(null);
  const [selectedHour, setSelectedHour] = useState<number | null>(null);
  const [sessionQuery, setSessionQuery] = useState("");
  // #54 per-row editor + merge selection
  const [editingSession, setEditingSession] = useState<number | null>(null);
  const [mergePicked, setMergePicked] = useState<number[]>([]);

  const load = useCallback(() => {
    api.activityDay(day).then(setData).catch(() => {});
  }, [day]);

  useEffect(load, [load, refreshKey]);

  useEffect(() => {
    setFilesLoading(true);
    api
      .filesActivity(filesHours)
      .then(setFiles)
      .catch(() => {})
      .finally(() => setFilesLoading(false));
  }, [filesHours, refreshKey]);

  useEffect(() => {
    api.activityWeek(rangeDays).then(setWeek).catch(() => {});
  }, [rangeDays, refreshKey]);

  useEffect(() => {
    api
      .activityTimeline(day, "task,note")
      .then((r) => setEvents(r.events))
      .catch(() => setEvents([]));
  }, [day, refreshKey]);

  useEffect(() => {
    api
      .activityGaps(day)
      .then((r) => setGaps(r.gaps))
      .catch(() => setGaps([]));
  }, [day, refreshKey]);

  useEffect(() => {
    api
      .activityProjects(day)
      .then((r) => setProjects(r.projects))
      .catch(() => setProjects([]));
  }, [day, refreshKey]);

  useEffect(() => {
    setSelectedHour(null);
  }, [day]);

  // Live session ticker (only meaningful for today)
  useEffect(() => {
    if (day !== todayLocal()) return;
    const t = window.setInterval(() => {
      api
        .liveSession()
        .then((r) => setLive(r.session))
        .catch(() => {});
    }, 5000);
    api.liveSession().then((r) => setLive(r.session)).catch(() => {});
    return () => window.clearInterval(t);
  }, [day]);

  async function togglePause() {
    if (!data) return;
    try {
      await api.pauseActivity(!data.paused);
      onToast(data.paused ? "activity logging resumed" : "activity logging paused");
      load();
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  function handleSelectApp(app: string) {
    setSelectedApp((cur) => (cur === app ? null : app));
  }

  const isToday = day === todayLocal();
  const total = data?.total_seconds ?? 0;
  const apps = data?.apps ?? [];
  const allSessions = data?.sessions ?? [];

  // #54 merges need a same-day selection; the API refuses anything else.
  const mergePickedSessions = allSessions.filter((s) => mergePicked.includes(s.id));

  const runMerge = async () => {
    if (mergePickedSessions.length < 2) {
      onToast("Pick at least two sessions to merge", "err");
      return;
    }
    if (new Set(mergePickedSessions.map((s) => s.day)).size > 1) {
      onToast("Sessions from different days cannot be merged", "err");
      return;
    }
    try {
      await api.mergeSessions([...mergePicked].sort((a, b) => a - b));
      onToast(`Merged ${mergePicked.length} sessions`);
      setMergePicked([]);
      load();
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    }
  };


  const appFilteredSessions = useMemo(
    () => (selectedApp ? allSessions.filter((s) => s.app_class === selectedApp) : allSessions),
    [allSessions, selectedApp],
  );

  const hours = useMemo(() => hourly(appFilteredSessions), [appFilteredSessions]);
  const peakHourObj = useMemo(() => {
    let best = hours[0];
    for (const h of hours) if (h.value > (best?.value ?? 0)) best = h;
    return best && best.value > 0 ? best : null;
  }, [hours]);

  const filteredSessions = useMemo(() => {
    const q = sessionQuery.trim().toLowerCase();
    return [...allSessions]
      .filter((s) => {
        if (selectedApp && s.app_class !== selectedApp) return false;
        if (selectedHour !== null) {
          const startH = new Date(s.first_seen).getHours();
          if (startH !== selectedHour) return false;
        }
        if (q) {
          return (
            s.app_class.toLowerCase().includes(q) ||
            prettyAppName(s.app_class).toLowerCase().includes(q) ||
            (s.title || "").toLowerCase().includes(q)
          );
        }
        return true;
      })
      .reverse();
  }, [allSessions, selectedApp, selectedHour, sessionQuery]);

  const weekBars = useMemo(
    () =>
      week.map((d) => ({
        key: d.day,
        label: shortDayLabel(d.day, rangeDays),
        value: d.seconds,
        sub: d.day === day ? "selected" : undefined,
        hint: `${prettyDay(d.day)} (${d.day}): ${fmtSecs(d.seconds)}`,
      })),
    [week, rangeDays, day],
  );

  const selectedDayIndex = useMemo(() => {
    const idx = week.findIndex((d) => d.day === day);
    return idx >= 0 ? idx : null;
  }, [week, day]);

  const activeAppObj = useMemo(
    () => (selectedApp ? apps.find((a) => a.app === selectedApp) ?? null : null),
    [apps, selectedApp],
  );

  const maxSessionSecs = useMemo(
    () => Math.max(...filteredSessions.map((s) => s.seconds), 1),
    [filteredSessions],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Docked Pane Toolbar */}
      <div className="app-toolbar flex h-11 shrink-0 items-center gap-2.5 px-4">
        <div className="flex items-center gap-1 rounded-lg border border-white/[0.07] bg-ink-950/80 p-0.5">
          <button
            onClick={() => setDay(shiftDay(day, -1))}
            className="rounded-md p-1 text-ink-300 transition-colors hover:bg-white/[0.07] hover:text-ink-100"
            title="Previous day"
          >
            <ChevronLeftIcon className="h-3.5 w-3.5" />
          </button>
          <div className="flex items-center gap-1.5 px-2">
            <CalendarIcon className="h-3.5 w-3.5 text-ember-400" />
            <span className="text-xs font-semibold text-ink-100">{prettyDay(day)}</span>
            <input
              type="date"
              value={day}
              max={todayLocal()}
              onChange={(e) => e.target.value && setDay(e.target.value)}
              className="cursor-pointer bg-transparent font-mono text-[11px] text-ink-400 outline-none hover:text-ember-300"
              title="Pick a date"
            />
          </div>
          <button
            onClick={() => setDay(shiftDay(day, 1))}
            disabled={isToday}
            className="rounded-md p-1 text-ink-300 transition-colors hover:bg-white/[0.07] hover:text-ink-100 disabled:opacity-30"
            title="Next day"
          >
            <ChevronRightIcon className="h-3.5 w-3.5" />
          </button>
        </div>

        {!isToday && (
          <button
            onClick={() => setDay(todayLocal())}
            className="rounded-lg border border-ember-500/30 bg-ember-500/12 px-2.5 py-1 text-xs font-medium text-ember-300 hover:bg-ember-500/20"
          >
            Today
          </button>
        )}

        {/* Active cross-filter badges */}
        {(selectedApp || selectedHour !== null) && (
          <div className="flex items-center gap-1.5">
            <FilterIcon className="h-3 w-3 text-ember-400" />
            {selectedApp && (
              <button
                onClick={() => setSelectedApp(null)}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2 py-0.5 text-xs font-medium text-ink-100 hover:border-ember-400/50"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: appColor(selectedApp) }}
                />
                {prettyAppName(selectedApp)}
                <XIcon className="h-2.5 w-2.5 text-ink-400" />
              </button>
            )}
            {selectedHour !== null && (
              <button
                onClick={() => setSelectedHour(null)}
                className="flex items-center gap-1 rounded-lg border border-iris-400/35 bg-iris-500/15 px-2 py-0.5 font-mono text-[11px] text-iris-300 hover:bg-iris-500/25"
              >
                {String(selectedHour).padStart(2, "0")}:00
                <XIcon className="h-2.5 w-2.5" />
              </button>
            )}
          </div>
        )}

        {/* Live Active Window Pill (Today) */}
        {isToday && !data?.paused && live && (
          <button
            onClick={() => handleSelectApp(live.app_class)}
            className="hidden items-center gap-2 rounded-lg border border-white/[0.07] bg-ink-950/75 px-2.5 py-1 text-xs transition-colors hover:border-white/15 lg:flex"
            title={`${prettyAppName(live.app_class)}: ${live.title}`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot" />
            <span
              className="font-semibold"
              style={{ color: appColor(live.app_class) }}
            >
              {prettyAppName(live.app_class)}
            </span>
            <span className="max-w-44 truncate text-ink-300">{live.title || live.app_class}</span>
            <span className="font-mono text-[10.5px] tabular-nums text-ink-400">
              {fmtSecs(live.seconds)}
            </span>
          </button>
        )}

        {/* Right KPI Counters & Pause Switch */}
        <div className="ml-auto flex items-center gap-3">
          <div className="hidden items-center gap-3 text-xs sm:flex">
            <span className="text-ink-400">
              Tracked <strong className="font-mono text-ember-300">{fmtSecs(total)}</strong>
            </span>
            <span className="text-ink-700">·</span>
            <span className="text-ink-400">
              Apps <strong className="font-mono text-iris-300">{apps.length}</strong>
            </span>
            <span className="text-ink-700">·</span>
            <span className="text-ink-400">
              Sessions <strong className="font-mono text-emerald-300">{allSessions.length}</strong>
            </span>
            {peakHourObj && (
              <>
                <span className="text-ink-700">·</span>
                <span className="hidden text-ink-400 xl:inline">
                  Peak <strong className="font-mono text-ink-100">{peakHourObj.label}:00</strong>
                </span>
              </>
            )}
          </div>

          {isToday && <PrivateBadge onToast={onToast} />}

          {isToday && (
            <button
              onClick={() => void togglePause()}
              className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                data?.paused
                  ? "border-ember-500/40 bg-ember-500/15 text-ember-300 hover:bg-ember-500/25"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
              }`}
              title="Pause/resume activity logging"
            >
              {data?.paused ? (
                <PlayIcon className="h-3 w-3" />
              ) : (
                <PauseIcon className="h-3 w-3" />
              )}
              {data?.paused ? "Resume" : "Logging"}
            </button>
          )}
        </div>
      </div>

      {/* Scrollable Workspace Body */}
      <div className="min-h-0 flex-1 space-y-3.5 overflow-y-auto p-4">
        {/* Row 1: Multi-day Activity Trend (3 cols) + Interactive App Time Split (2 cols) */}
        <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-5">
          {/* Multi-range Activity Chart */}
          <div className="glass-studio flex flex-col justify-between rounded-2xl p-4 xl:col-span-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="micro-label flex items-center gap-1.5">
                  <ClockIcon className="h-3.5 w-3.5 text-ember-400" /> Activity Trend — Click any day to inspect
                </p>
                <p className="mt-0.5 text-xs text-ink-400">
                  <span className="font-mono font-semibold text-ink-200">
                    {fmtSecs(week.reduce((s, d) => s + d.seconds, 0))}
                  </span>{" "}
                  tracked across the last {rangeDays} days
                </p>
                {/* #58 switches, #62 today vs the recent average */}
                <div className="mt-1.5">
                  <FocusMetrics day={day} />
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                {/* #342 the same numbers, out of the app — sessions or a
                    day×project timesheet over the visible range. */}
                <a
                  href={api.activityExportUrl("csv", { day_from: shiftDay(day, -(rangeDays - 1)), day_to: day })}
                  download
                  title="Download the visible range as CSV"
                  aria-label="Export sessions as CSV"
                  className="rounded-lg border border-white/[0.06] bg-ink-950/90 px-2 py-1 font-mono text-[10px] text-ink-400 transition-colors hover:text-ember-300"
                >
                  CSV
                </a>
                <a
                  href={api.activityExportUrl("timesheet", { day_from: shiftDay(day, -(rangeDays - 1)), day_to: day })}
                  download
                  title="Download a project timesheet as CSV"
                  aria-label="Export timesheet as CSV"
                  className="rounded-lg border border-white/[0.06] bg-ink-950/90 px-2 py-1 font-mono text-[10px] text-ink-400 transition-colors hover:text-ember-300"
                >
                  Timesheet
                </a>
                <div className="flex rounded-lg border border-white/[0.06] bg-ink-950/90 p-0.5 text-[10px]">
                  {([7, 14, 30] as const).map((r) => (
                    <button
                      key={r}
                      onClick={() => setRangeDays(r)}
                      className={`rounded-md px-2 py-0.5 font-mono transition-colors ${
                        rangeDays === r
                          ? "bg-ember-500/20 font-semibold text-ember-300"
                          : "text-ink-400 hover:text-ink-200"
                      }`}
                    >
                      {r}D
                    </button>
                  ))}
                </div>
                <div className="flex rounded-lg border border-white/[0.06] bg-ink-950/90 p-0.5 text-[10px]">
                  <button
                    onClick={() => setTrendMode("bars")}
                    className={`rounded-md px-2 py-0.5 transition-colors ${
                      trendMode === "bars"
                        ? "bg-iris-500/25 font-medium text-iris-300"
                        : "text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    Bars
                  </button>
                  <button
                    onClick={() => setTrendMode("area")}
                    className={`rounded-md px-2 py-0.5 transition-colors ${
                      trendMode === "area"
                        ? "bg-iris-500/25 font-medium text-iris-300"
                        : "text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    Curve
                  </button>
                </div>
              </div>
            </div>

            {week.length > 0 ? (
              trendMode === "bars" ? (
                <Bars
                  data={weekBars}
                  color="#c8643b"
                  height={120}
                  format={fmtSecs}
                  showAvg
                  selectedIndex={selectedDayIndex}
                  onSelect={(_idx, item) => item.key && setDay(item.key)}
                />
              ) : (
                <AreaTrend
                  data={weekBars}
                  color="#c8643b"
                  height={120}
                  format={fmtSecs}
                  showAvg
                  selectedIndex={selectedDayIndex}
                  onSelect={(_idx, item) => item.key && setDay(item.key)}
                />
              )
            ) : (
              <div className="shimmer h-[144px] rounded-xl" />
            )}
          </div>

          {/* Interactive Donut & App Time Split */}
          <div className="glass-studio flex flex-col justify-between rounded-2xl p-4 xl:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <p className="micro-label">Application Focus — Click to filter</p>
              {selectedApp && (
                <button
                  onClick={() => setSelectedApp(null)}
                  className="text-[11px] font-medium text-ember-300 hover:underline"
                >
                  Clear filter
                </button>
              )}
            </div>

            {/* #63 point at a stretch and ask about it */}
            <RangeAsk day={day} onOpenNote={onOpenNote} onToast={onToast} />

            {/* #59 the long view: a year of days in one glance */}
            <ActivityHeatmap onOpenDay={setDay} />

            {/* #337 holes in the record, with a way to fill them */}
            <GapCard gaps={gaps} onFilled={load} onToast={onToast} />

            {/* #53 projects — detected at write time, so this is what was
                actually worked on, not a re-read of today's titles */}
            {projects.length > 0 && (
              <div className="mb-3 border-t border-white/[0.06] pt-3">
                <p className="micro-label mb-1.5">Projects</p>
                <div className="flex flex-wrap gap-1.5">
                  {projects.slice(0, 8).map((p) => (
                    <span
                      key={p.project ?? "(none)"}
                      className="rounded-lg border border-ink-800 bg-ink-900/60 px-2 py-1 font-mono text-[10.5px] text-ink-200"
                      title={`${p.project ?? "unlabelled"} — ${fmtSecs(p.seconds)}`}
                    >
                      {p.project ?? "unlabelled"}
                      <span className="ml-1.5 text-ink-400">{fmtSecs(p.seconds)}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {apps.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center py-6 text-center">
                <p className="text-xs text-ink-400">No app activity recorded for {prettyDay(day)}.</p>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-4">
                  <Donut
                    segments={apps.slice(0, 8).map((a) => ({
                      key: a.app,
                      value: a.seconds,
                      color: appColor(a.app),
                      label: `${prettyAppName(a.app)} — ${fmtSecs(a.seconds)}`,
                      formatted: fmtSecs(a.seconds),
                    }))}
                    size={132}
                    thickness={14}
                    centerTop={fmtSecs(total)}
                    centerSub={`${apps.length} apps`}
                    selectedKey={selectedApp}
                    onSelect={handleSelectApp}
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    {apps.slice(0, 5).map((a) => {
                      const isSel = selectedApp === a.app;
                      const color = appColor(a.app);
                      const pct = Math.max(2, Math.round((a.seconds / Math.max(total, 1)) * 100));
                      return (
                        <button
                          key={a.app}
                          onClick={() => handleSelectApp(a.app)}
                          className={`group flex w-full flex-col gap-1 rounded-lg px-2 py-1 text-left transition-all ${
                            isSel
                              ? "bg-white/[0.09] ring-1 ring-white/15"
                              : "hover:bg-white/[0.04]"
                          }`}
                        >
                          <div className="flex items-center gap-2 text-xs">
                            <span
                              className="flex h-4 w-4 shrink-0 items-center justify-center rounded text-[9px] font-bold text-ink-950"
                              style={{ background: color }}
                            >
                              {appMonogram(a.app)}
                            </span>
                            <span className="truncate font-medium text-ink-100">
                              {prettyAppName(a.app)}
                            </span>
                            <span className="ml-auto shrink-0 font-mono text-[10.5px] tabular-nums text-ink-300">
                              {fmtSecs(a.seconds)}{" "}
                              <span className="text-ink-500">· {pct}%</span>
                            </span>
                          </div>
                          <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.05]">
                            <div
                              className="h-full rounded-full transition-all duration-300"
                              style={{ width: `${pct}%`, background: color }}
                            />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {activeAppObj && activeAppObj.titles.length > 0 && (
                  <div className="mt-3 rounded-xl border border-white/[0.06] bg-ink-950/65 p-2.5">
                    <p
                      className="micro-label mb-1.5 !text-[9.5px]"
                      style={{ color: appColor(activeAppObj.app) }}
                    >
                      Top windows in {prettyAppName(activeAppObj.app)}
                    </p>
                    <div className="space-y-1">
                      {activeAppObj.titles.slice(0, 3).map((t, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-[11px]">
                          <span className="truncate text-ink-200">{t.title || "(untitled)"}</span>
                          <span className="ml-auto shrink-0 font-mono tabular-nums text-ink-400">
                            {fmtSecs(t.seconds)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Row 2: 24-Hour Session Ribbon + Hourly Rhythm (3 cols) | AI Daily Report (2 cols) */}
        <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-5">
          <div className="glass-studio space-y-4 rounded-2xl p-4 xl:col-span-3">
            <div>
              <div className="mb-2 flex items-baseline justify-between">
                <p className="micro-label flex items-center gap-1.5">
                  <ActivityIcon className="h-3.5 w-3.5 text-cyan-400" /> 24-Hour Session Ribbon
                </p>
                <span className="text-[10.5px] text-ink-400">
                  Hover to inspect · Click block to filter app
                </span>
              </div>
              <SessionRibbon
                sessions={allSessions}
                selectedApp={selectedApp}
                onSelectApp={handleSelectApp}
                isToday={isToday}
                markers={events.map((e) => ({
                  kind: e.kind as "task" | "note",
                  id: String(e.id),
                  at: e.at,
                  label: e.label,
                }))}
                onMarkerClick={(m) => {
                  if (m.kind === "note") onOpenNote?.(m.id);
                  else onToast(`finished task: ${m.label}`);
                }}
              />
            </div>

            <div className="border-t border-white/[0.06] pt-3.5">
              <div className="mb-2 flex items-baseline justify-between">
                <p className="micro-label">
                  Hourly Intensity {selectedApp ? `(${prettyAppName(selectedApp)})` : ""} — Click hour to filter feed
                </p>
                <p className="font-mono text-xs tabular-nums text-ink-400">
                  peak {fmtSecs(Math.max(...hours.map((h) => h.value), 0))}
                </p>
              </div>
              <Bars
                data={hours.map((h, idx) => ({
                  ...h,
                  label: idx % 3 === 0 ? h.label : "",
                  color: selectedApp ? appColor(selectedApp) : "#74875c",
                }))}
                color="#74875c"
                height={88}
                format={fmtSecs}
                highlightLast={false}
                selectedIndex={selectedHour}
                onSelect={(idx) => setSelectedHour((cur) => (cur === idx ? null : idx))}
              />
            </div>
          </div>

        </div>

        {/* Row 3: Files & Git Activity + Interactive Session Feed */}
        <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-5">
          {/* Files & Git Activity */}
          <div className="glass rounded-2xl p-4 xl:col-span-2">
            <div className="mb-3 flex items-center justify-between">
              <p className="micro-label flex items-center gap-1.5">
                <FileIcon className="h-3.5 w-3.5 text-ember-400" /> Workspace Files & Commits
              </p>
              <div className="flex rounded-lg border border-white/[0.06] bg-ink-950/90 p-0.5 text-[10px]">
                {[
                  { label: "24h", h: 24 },
                  { label: "48h", h: 48 },
                  { label: "7d", h: 168 },
                ].map((opt) => (
                  <button
                    key={opt.h}
                    onClick={() => setFilesHours(opt.h)}
                    className={`rounded-md px-2 py-0.5 font-mono transition-colors ${
                      filesHours === opt.h
                        ? "bg-ember-500/20 font-semibold text-ember-300"
                        : "text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {filesLoading && !files ? (
              <div className="space-y-2 py-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="shimmer h-12 rounded-xl" />
                ))}
              </div>
            ) : !files || files.total === 0 ? (
              <p className="py-6 text-center text-xs text-ink-400">
                No recently modified files in watched directories.
              </p>
            ) : (
              <div className="space-y-2">
                {files.groups.slice(0, 6).map((g) => {
                  const isExp = expandedGroup === g.label;
                  const color = appColor(g.label);
                  return (
                    <div
                      key={g.label}
                      onClick={() => setExpandedGroup(isExp ? null : g.label)}
                      className="cursor-pointer rounded-xl border border-white/[0.06] bg-ink-950/60 p-2.5 transition-colors hover:border-white/15"
                    >
                      <div className="flex items-center gap-2 text-xs">
                        <span className="shrink-0" style={{ color }}>
                          <FolderIcon className="h-3.5 w-3.5" />
                        </span>
                        <span className="truncate font-semibold text-ink-100">{g.label}</span>
                        <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-ember-300">
                          {g.count} {g.count === 1 ? "file" : "files"}
                        </span>
                        <div className="ml-auto flex shrink-0 items-center gap-1">
                          {g.exts.slice(0, 3).map(([e, n]) => (
                            <span
                              key={e}
                              className="rounded bg-white/[0.04] px-1.5 py-0.2 font-mono text-[9.5px] text-ink-300"
                            >
                              {e} <strong className="text-ink-100">{n}</strong>
                            </span>
                          ))}
                        </div>
                      </div>
                      {isExp ? (
                        <ul className="mt-2 space-y-1 border-t border-white/[0.06] pt-2 font-mono text-[11px] text-ink-300">
                          {g.samples.map((s, idx) => (
                            <li key={idx} className="truncate">
                              · {s}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-1 truncate font-mono text-[10.5px] text-ink-400">
                          {g.samples[0]}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            {files && files.git.length > 0 && (
              <div className="mt-3 border-t border-white/[0.06] pt-3">
                <p className="micro-label mb-2 flex items-center gap-1.5">
                  <GitCommitIcon className="h-3.5 w-3.5 text-iris-400" /> Recent Git Commits
                </p>
                <div className="space-y-1.5">
                  {files.git.map((r) => (
                    <div
                      key={r.repo}
                      className="rounded-xl border border-white/[0.06] bg-ink-950/50 px-3 py-2 text-xs"
                    >
                      <span className="font-mono font-semibold text-iris-300">{r.repo}</span>
                      <p className="mt-0.5 truncate text-ink-200">{r.subjects[0]}</p>
                      {r.subjects.length > 1 && (
                        <p className="mt-0.5 font-mono text-[10px] text-ink-500">
                          +{r.subjects.length - 1} more commit{r.subjects.length - 1 > 1 ? "s" : ""}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Interactive Session Feed */}
          <div className="glass rounded-2xl p-4 xl:col-span-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="micro-label">
                Session Feed — {filteredSessions.length} of {allSessions.length} shown
              </p>
              {mergePicked.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[10.5px] text-ember-300">
                    {mergePicked.length} picked
                  </span>
                  <button
                    onClick={() => void runMerge()}
                    className="rounded-lg border border-ember-500/30 bg-ember-500/10 px-2.5 py-1 text-[11px] text-ember-300 hover:bg-ember-500/20"
                  >
                    Merge
                  </button>
                  <button
                    onClick={() => setMergePicked([])}
                    aria-label="Clear merge selection"
                    className="rounded-lg border border-ink-700 px-2 py-1 text-[11px] text-ink-400"
                  >
                    ✕
                  </button>
                </div>
              )}
              <div className="relative w-56">
                <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 h-3 w-3 -translate-y-1/2 text-ink-400" />
                <input
                  value={sessionQuery}
                  onChange={(e) => setSessionQuery(e.target.value)}
                  placeholder="Filter app or window title…"
                  className="h-7 w-full rounded-lg border border-white/[0.07] bg-ink-950/80 pr-6 pl-7 text-xs text-ink-100 placeholder-ink-500 outline-none focus:border-ember-500/50"
                />
                {sessionQuery && (
                  <button
                    onClick={() => setSessionQuery("")}
                    className="absolute top-1/2 right-2 -translate-y-1/2 text-ink-400 hover:text-ink-200"
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>

            {filteredSessions.length === 0 ? (
              <p className="py-8 text-center text-xs text-ink-400">
                No sessions match the current filters.
              </p>
            ) : (
              <div className="max-h-80 space-y-1 overflow-y-auto pr-1">
                {filteredSessions.map((s) => {
                  const color = appColor(s.app_class);
                  const barPct = Math.max(5, Math.round((s.seconds / maxSessionSecs) * 100));
                  return (
                    <div
                      key={s.id}
                      className="group flex items-center gap-2.5 rounded-xl border border-transparent bg-white/[0.015] rise px-2.5 py-1.5 transition-colors hover:border-white/[0.06] hover:bg-white/[0.04]"
                    >
                      <input
                        type="checkbox"
                        checked={mergePicked.includes(s.id)}
                        onChange={() =>
                          setMergePicked((p) =>
                            p.includes(s.id) ? p.filter((i) => i !== s.id) : [...p, s.id],
                          )
                        }
                        aria-label={`Select ${s.app_class} session for merge`}
                        className="h-3 w-3 shrink-0 accent-ember-500"
                      />
                      <button
                        onClick={() => setEditingSession((id) => (id === s.id ? null : s.id))}
                        aria-expanded={editingSession === s.id}
                        aria-label={`Edit ${s.app_class} session`}
                        title="Edit this session"
                        className="shrink-0 rounded px-1 font-mono text-[10px] text-ink-500 hover:text-ember-300"
                      >
                        {editingSession === s.id ? "▾" : "▸"}
                      </button>
                      <span className="w-16 shrink-0 font-mono text-[10.5px] tabular-nums text-ink-400">
                        {hhmm(s.first_seen)}
                      </span>
                      <button
                        onClick={() => handleSelectApp(s.app_class)}
                        className="flex shrink-0 items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-medium transition-transform hover:scale-105"
                        style={{
                          background: color + "1f",
                          color,
                        }}
                        title={`Filter by ${s.app_class}`}
                      >
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ background: color }}
                        />
                        {prettyAppName(s.app_class)}
                      </button>
                      <span className="selectable min-w-0 flex-1 truncate text-xs text-ink-200">
                        {s.title || "(untitled window)"}
                      </span>
                      <div className="hidden w-20 items-center sm:flex">
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${barPct}%`, background: color }}
                          />
                        </div>
                      </div>
                      <span className="w-12 shrink-0 text-right font-mono text-[11px] font-medium tabular-nums text-ink-200">
                        {fmtSecs(s.seconds)}
                      </span>
                    </div>
                  );
                })}
                {editingSession !== null && (() => {
                  const target = filteredSessions.find((s) => s.id === editingSession);
                  if (!target) return null;
                  return (
                    <SessionEditor
                      session={target}
                      onDone={() => setEditingSession(null)}
                      onChanged={load}
                      onToast={onToast}
                    />
                  );
                })()}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
