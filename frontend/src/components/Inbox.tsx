import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { dayGroup } from "../time";
import { AreaTrend, Bars, Ring, StackBar } from "./charts";
import NoteCard from "./NoteCard";
import { runNoteAction } from "./actionRunner";
import {
  ActivityIcon,
  FilterIcon,
  GridIcon,
  LinkIcon,
  ListIcon,
  MicIcon,
  PinIcon,
  SearchIcon,
  SparkIcon,
  TextIcon,
  TrashIcon,
  XIcon,
} from "./Icons";
import type { Note, Stats } from "../types";

interface Props {
  notes: Note[];
  selectedId?: string | null;
  onOpen: (id: string) => void;
  onPin: (id: string) => void;
  onQuickStart: () => void;
  onNoteUpdated?: (note: Note) => void;
  onNoteDeleted?: (id: string) => void;
  onToast?: (message: string, kind?: "ok" | "err") => void;
}

function dayLabel(d: string, total: number) {
  const dt = new Date(d + "T12:00:00");
  if (total <= 7) return dt.toLocaleDateString([], { weekday: "short" });
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
}

export default function Inbox({
  notes,
  selectedId,
  onOpen,
  onPin,
  onQuickStart,
  onNoteUpdated,
  onNoteDeleted,
  onToast,
}: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [rangeDays, setRangeDays] = useState<7 | 14 | 30>(7);
  const [chartMode, setChartMode] = useState<"bars" | "area">("bars");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [filterQuery, setFilterQuery] = useState("");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [showMetrics, setShowMetrics] = useState(true);
  const [showFailed, setShowFailed] = useState(false);

  // Every mutation below used to swallow its error, so a failed delete left the
  // note on screen with no explanation. Toast the outcome instead.
  const toast = onToast ?? ((message: string) => void message);
  const refreshStats = useCallback(
    () => api.stats(rangeDays).then(setStats).catch(() => {}),
    [rangeDays],
  );

  useEffect(() => {
    refreshStats();
  }, [refreshStats, notes.length]);

  async function handleToggleTask(note: Note, itemId: string) {
    const items = note.action_items.map((it) =>
      it.id === itemId ? { ...it, done: !it.done } : it,
    );
    await runNoteAction({
      api,
      toast,
      action: () => api.updateNote(note.id, { action_items: items } as Partial<Note>),
      success: "Task updated",
      onDone: (updated) => {
        onNoteUpdated?.(updated);
        void refreshStats();
      },
    });
  }

  async function handleRetry(id: string) {
    await runNoteAction({
      api,
      toast,
      action: () => api.reprocess(id),
      success: "Reprocessing started",
      onDone: (updated) => onNoteUpdated?.(updated),
    });
  }

  async function handleDelete(id: string) {
    await runNoteAction({
      api,
      toast,
      action: () => api.deleteNote(id),
      success: "Note deleted",
      onDone: () => {
        onNoteDeleted?.(id);
        void refreshStats();
      },
    });
  }

  async function handleClearFailed(failedNotes: Note[]) {
    for (const n of failedNotes) {
      await runNoteAction({
        api,
        toast,
        action: () => api.deleteNote(n.id),
        success: `Cleared ${failedNotes.length} failed capture${failedNotes.length === 1 ? "" : "s"}`,
        onDone: () => onNoteDeleted?.(n.id),
      });
    }
    void refreshStats();
  }

  const activeNotes = useMemo(() => notes.filter((n) => !n.archived), [notes]);

  // Separate empty failed captures (e.g. silent mic checks) so they don't clutter the primary workspace
  const { healthyNotes, emptyFailedNotes } = useMemo(() => {
    const healthy: Note[] = [];
    const failedEmpty: Note[] = [];
    for (const n of activeNotes) {
      if (n.status === "failed" && !n.title?.trim() && !n.raw_text?.trim()) {
        failedEmpty.push(n);
      } else {
        healthy.push(n);
      }
    }
    return { healthyNotes: healthy, emptyFailedNotes: failedEmpty };
  }, [activeNotes]);

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = { text: 0, voice: 0, youtube: 0 };
    for (const n of healthyNotes) {
      c[n.type] = (c[n.type] ?? 0) + 1;
    }
    return c;
  }, [healthyNotes]);

  const filteredNotes = useMemo(() => {
    const q = filterQuery.trim().toLowerCase();
    const pool = showFailed ? activeNotes : healthyNotes;
    return pool.filter((n) => {
      if (typeFilter !== "all" && n.type !== typeFilter) return false;
      if (tagFilter && !n.tags.includes(tagFilter)) return false;
      if (q) {
        return (
          (n.title || "").toLowerCase().includes(q) ||
          (n.summary || "").toLowerCase().includes(q) ||
          (n.raw_text || "").toLowerCase().includes(q) ||
          n.tags.some((t) => t.toLowerCase().includes(q))
        );
      }
      return true;
    });
  }, [activeNotes, healthyNotes, showFailed, typeFilter, tagFilter, filterQuery]);

  const pinned = filteredNotes.filter((n) => n.pinned);
  const rest = filteredNotes.filter((n) => !n.pinned);

  const groups: Array<[string, Note[]]> = [];
  for (const note of rest) {
    const label = dayGroup(note.created_at);
    const last = groups[groups.length - 1];
    if (last && last[0] === label) last[1].push(note);
    else groups.push([label, [note]]);
  }

  const completion =
    stats && stats.done_tasks + stats.open_tasks > 0
      ? stats.done_tasks / (stats.done_tasks + stats.open_tasks)
      : 0;

  const chartData = useMemo(
    () =>
      (stats?.notes_per_day ?? []).map((d) => ({
        key: d.day,
        label: dayLabel(d.day, rangeDays),
        value: d.count,
        hint: `${d.day}: ${d.count} captures`,
      })),
    [stats, rangeDays],
  );

  const gridCls =
    layout === "list"
      ? "space-y-2"
      : selectedId
        ? "grid grid-cols-1 gap-3 2xl:grid-cols-2"
        : "grid grid-cols-1 gap-3 md:grid-cols-2";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Docked Pane Toolbar */}
      <div className="app-toolbar flex h-11 shrink-0 items-center gap-2 px-4">
        <div className="flex items-center gap-1 rounded-lg border border-white/[0.06] bg-ink-950/80 p-0.5 text-xs">
          {[
            { id: "all", label: "All", count: healthyNotes.length, icon: null },
            {
              id: "text",
              label: "Notes",
              count: typeCounts.text,
              icon: <TextIcon className="h-3 w-3 text-ember-400" />,
            },
            {
              id: "voice",
              label: "Voice",
              count: typeCounts.voice,
              icon: <MicIcon className="h-3 w-3 text-iris-400" />,
            },
            {
              id: "youtube",
              label: "YouTube",
              count: typeCounts.youtube,
              icon: <LinkIcon className="h-3 w-3 text-cyan-400" />,
            },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setTypeFilter(tab.id)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 transition-all ${
                typeFilter === tab.id
                  ? "bg-white/[0.09] font-semibold text-ink-100 shadow-xs"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
              <span className="font-mono text-[10px] tabular-nums text-ink-400">{tab.count}</span>
            </button>
          ))}
        </div>

        {tagFilter && (
          <button
            onClick={() => setTagFilter(null)}
            className="flex items-center gap-1 rounded-md border border-ember-400/40 bg-ember-500/15 px-2 py-1 text-xs font-medium text-ember-200 hover:bg-ember-500/25"
          >
            <FilterIcon className="h-3 w-3" /> #{tagFilter}
            <XIcon className="h-3 w-3" />
          </button>
        )}

        {emptyFailedNotes.length > 0 && (
          <div className="hidden shrink-0 items-center gap-1 rounded-lg border border-red-500/25 bg-red-500/8 px-2 py-0.5 text-[11px] whitespace-nowrap text-red-200 md:flex">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
            <span>{emptyFailedNotes.length} failed</span>
            <button
              onClick={() => setShowFailed((v) => !v)}
              className="ml-0.5 rounded px-1.5 py-0.5 font-medium text-ink-200 hover:bg-white/10"
            >
              {showFailed ? "Hide" : "Show"}
            </button>
            <button
              onClick={() => void handleClearFailed(emptyFailedNotes)}
              className="flex items-center gap-1 rounded px-1.5 py-0.5 font-medium text-red-300 hover:bg-red-500/20"
              title="Delete all empty failed captures"
            >
              <TrashIcon className="h-3 w-3" /> Clear
            </button>
          </div>
        )}

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <div className="relative w-36 lg:w-48">
            <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
            <input
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Filter inbox…"
              className="h-7 w-full rounded-lg border border-white/[0.07] bg-ink-950/90 pr-6 pl-7.5 text-xs text-ink-100 placeholder-ink-500 outline-none transition-colors focus:border-ember-500/50"
            />
            {filterQuery && (
              <button
                onClick={() => setFilterQuery("")}
                className="absolute top-1/2 right-1.5 -translate-y-1/2 text-ink-400 hover:text-ink-200"
              >
                <XIcon className="h-3 w-3" />
              </button>
            )}
          </div>

          <button
            onClick={() => setShowMetrics((v) => !v)}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              showMetrics
                ? "border-iris-400/35 bg-iris-500/15 text-iris-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Toggle telemetry deck"
          >
            <ActivityIcon className="h-3 w-3" />
            <span className="hidden lg:inline">Overview</span>
          </button>

          <div className="flex rounded-lg border border-white/[0.07] bg-ink-950/80 p-0.5">
            <button
              onClick={() => setLayout("grid")}
              className={`rounded-md p-1 transition-colors ${
                layout === "grid"
                  ? "bg-white/[0.1] text-ember-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
              title="Grid view"
            >
              <GridIcon className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setLayout("list")}
              className={`rounded-md p-1 transition-colors ${
                layout === "list"
                  ? "bg-white/[0.1] text-ember-300"
                  : "text-ink-400 hover:text-ink-200"
              }`}
              title="List view"
            >
              <ListIcon className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Scrollable Workspace Body */}
      <div className="min-h-0 flex-1 overflow-y-auto p-4 space-y-5">
        <div className="px-1 pb-1 pt-4">
          <p className="micro-label mb-3">Your vault{stats ? ` · ${stats.total} captures` : ""}</p>
          <h1 className="hero-title max-w-3xl text-[clamp(2.4rem,5vw,4rem)]">
            Passing thoughts, <em>kept</em> and ready when you are.
          </h1>
        </div>
        {/* Elevated 3-Card Telemetry Deck */}
        {showMetrics && (
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-12 min-h-[220px]">
            {!stats ? (
              <>
                <div className="skeleton-card rounded-2xl xl:col-span-4"></div>
                <div className="skeleton-card rounded-2xl xl:col-span-5"></div>
                <div className="skeleton-card rounded-2xl xl:col-span-3"></div>
              </>
            ) : (
              <>
                {/* Card 1: Capture Mix & Totals (4 cols) */}
                <div className="glass-studio stagger-1 flex flex-col justify-between rounded-2xl p-4 xl:col-span-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="micro-label">Today</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <p className="stat-number text-2xl leading-none counter-up-anim">{stats.today}</p>
                        {stats.today > 0 && (
                          <span className={`flex items-center text-[10px] font-medium ${stats.today >= stats.week / 7 ? 'text-emerald-500' : 'text-ember-500'}`}>
                            {stats.today >= stats.week / 7 ? (
                              <svg className="h-3 w-3 mr-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" /></svg>
                            ) : (
                              <svg className="h-3 w-3 mr-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M19 14l-7 7m0 0l-7-7m7 7V3" /></svg>
                            )}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="border-l border-white/[0.07] pl-4">
                      <p className="micro-label">7-Day</p>
                      <p className="stat-number-iris mt-0.5 text-2xl leading-none counter-up-anim">{stats.week}</p>
                    </div>
                    <div className="border-l border-white/[0.07] pl-4">
                      <p className="micro-label">Vault Total</p>
                      <p className="stat-number-emerald mt-0.5 text-2xl leading-none counter-up-anim">
                        {healthyNotes.length}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4">
                    <StackBar
                      height={7}
                      segments={[
                        {
                          key: "text",
                          value: typeCounts.text || 0,
                          color: "#bd5d38",
                          title: `Notes: ${typeCounts.text}`,
                        },
                        {
                          key: "voice",
                          value: typeCounts.voice || 0,
                          color: "#74875c",
                          title: `Voice: ${typeCounts.voice}`,
                        },
                        {
                          key: "youtube",
                          value: typeCounts.youtube || 0,
                          color: "#4b786b",
                          title: `YouTube: ${typeCounts.youtube}`,
                        },
                      ]}
                      selectedKey={typeFilter === "all" ? null : typeFilter}
                      onSelect={(k) => setTypeFilter((cur) => (cur === k ? "all" : k))}
                    />
                    <div className="mt-2 flex items-center justify-between text-[11px] text-ink-300">
                      <button
                        onClick={() => setTypeFilter((c) => (c === "text" ? "all" : "text"))}
                        className="relative flex items-center gap-1.5 hover:text-ink-100 after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:origin-right after:scale-x-0 after:bg-current after:transition-transform hover:after:origin-left hover:after:scale-x-100"
                      >
                        <span className="h-2 w-2 rounded-full bg-ember-400" />
                        <span>Notes</span>
                        <span className="font-mono text-ink-400">{typeCounts.text}</span>
                      </button>
                      <button
                        onClick={() => setTypeFilter((c) => (c === "voice" ? "all" : "voice"))}
                        className="relative flex items-center gap-1.5 hover:text-ink-100 after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:origin-right after:scale-x-0 after:bg-current after:transition-transform hover:after:origin-left hover:after:scale-x-100"
                      >
                        <span className="h-2 w-2 rounded-full bg-iris-400" />
                        <span>Voice</span>
                        <span className="font-mono text-ink-400">{typeCounts.voice}</span>
                      </button>
                      <button
                        onClick={() => setTypeFilter((c) => (c === "youtube" ? "all" : "youtube"))}
                        className="relative flex items-center gap-1.5 hover:text-ink-100 after:absolute after:-bottom-1 after:left-0 after:h-px after:w-full after:origin-right after:scale-x-0 after:bg-current after:transition-transform hover:after:origin-left hover:after:scale-x-100"
                      >
                        <span className="h-2 w-2 rounded-full bg-cyan-400" />
                        <span>YouTube</span>
                        <span className="font-mono text-ink-400">{typeCounts.youtube}</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Card 2: Capture Velocity Chart (5 cols) */}
                <div className="glass-studio stagger-2 flex flex-col justify-between rounded-2xl p-4 xl:col-span-5">
                  <div className="mb-2 flex items-center justify-between">
                    <div>
                      <p className="micro-label">Capture Velocity ({rangeDays}d)</p>
                      <p className="mt-0.5 font-mono text-[11px] text-ink-400">
                        <span className="font-semibold text-ink-200">
                          {chartData.reduce((s, d) => s + d.value, 0)} captures
                        </span>
                        {" · "}
                        {(
                          chartData.reduce((s, d) => s + d.value, 0) / Math.max(chartData.length, 1)
                        ).toFixed(1)}
                        /day avg
                      </p>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="flex rounded-md border border-white/[0.06] bg-ink-950/90 p-0.5 text-[9.5px]">
                        {([7, 14, 30] as const).map((r) => (
                          <button
                            key={r}
                            onClick={() => setRangeDays(r)}
                            className={`rounded px-1.5 py-0.5 font-mono transition-colors ${
                              rangeDays === r
                                ? "bg-iris-500/25 font-semibold text-iris-300"
                                : "text-ink-400 hover:text-ink-200"
                            }`}
                          >
                            {r}D
                          </button>
                        ))}
                      </div>
                      <div className="flex rounded-md border border-white/[0.06] bg-ink-950/90 p-0.5 text-[9.5px]">
                        <button
                          onClick={() => setChartMode("bars")}
                          className={`rounded px-1.5 py-0.5 transition-colors ${
                            chartMode === "bars"
                              ? "bg-ember-500/20 font-medium text-ember-300"
                              : "text-ink-400 hover:text-ink-200"
                          }`}
                        >
                          Bars
                        </button>
                        <button
                          onClick={() => setChartMode("area")}
                          className={`rounded px-1.5 py-0.5 transition-colors ${
                            chartMode === "area"
                              ? "bg-ember-500/20 font-medium text-ember-300"
                              : "text-ink-400 hover:text-ink-200"
                          }`}
                        >
                          Curve
                        </button>
                      </div>
                    </div>
                  </div>
                  {chartMode === "bars" ? (
                    <Bars data={chartData} color="#5e826b" height={90} highlightLast showAvg />
                  ) : (
                    <AreaTrend data={chartData} color="#5e826b" height={90} showAvg />
                  )}
                </div>

                {/* Card 3: Task Completion Ring (3 cols) */}
                <div className="glass-studio stagger-3 flex items-center gap-3.5 rounded-2xl p-4 xl:col-span-3">
                  <Ring
                    progress={completion}
                    color="#10b981"
                    size={66}
                    thickness={6}
                    label={`${Math.round(completion * 100)}%`}
                    sub="done"
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="micro-label">Action Items</p>
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-ink-300">Done</span>
                        <span className="font-mono font-semibold tabular-nums text-emerald-300">
                          {stats.done_tasks}
                        </span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-ink-300">Open</span>
                        <span className="font-mono font-semibold tabular-nums text-ember-300">
                          {stats.open_tasks}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* Notes Feed */}
        {notes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="glass-studio flex h-14 w-14 items-center justify-center rounded-2xl">
              <SparkIcon className="h-6 w-6 text-ember-400" />
            </div>
            <h2 className="mt-4 text-base font-semibold text-ink-100">Inbox is empty</h2>
            <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-400">
              Use the top command bar (<kbd className="font-mono text-ember-300">n</kbd>) to capture
              a note, voice memo, or YouTube video.
            </p>
            <button
              onClick={onQuickStart}
              className="mt-4 rounded-lg border border-white/10 bg-ink-900 px-3.5 py-1.5 text-xs font-medium text-ink-200 hover:border-ember-400/40"
            >
              Focus capture bar
            </button>
          </div>
        ) : filteredNotes.length === 0 ? (
          <div className="glass rounded-2xl py-12 text-center">
            <p className="text-xs text-ink-400">No captures match the active filters.</p>
            <button
              onClick={() => {
                setTypeFilter("all");
                setTagFilter(null);
                setFilterQuery("");
              }}
              className="mt-2 text-xs font-medium text-ember-300 hover:underline"
            >
              Reset filters
            </button>
          </div>
        ) : (
          <div className="space-y-5">
            {pinned.length > 0 && (
              <section>
                <div className="mb-2.5 flex items-center gap-2 px-1">
                  <PinIcon filled className="h-3.5 w-3.5 text-ember-400" />
                  <h2 className="micro-label !text-ember-300">Pinned Captures</h2>
                  <span className="rounded-full bg-ember-500/15 px-2 py-0.2 font-mono text-[10px] font-semibold text-ember-300">
                    {pinned.length}
                  </span>
                </div>
                <div className={gridCls}>
                  {pinned.map((n) => (
                    <NoteCard
                      key={n.id}
                      note={n}
                      highlight={selectedId === n.id}
                      onOpen={onOpen}
                      onPin={onPin}
                      onTagClick={(t) => setTagFilter((cur) => (cur === t ? null : t))}
                      onToggleTask={handleToggleTask}
                      onRetry={handleRetry}
                      onDelete={handleDelete}
                    />
                  ))}
                </div>
              </section>
            )}

            {groups.map(([label, items]) => (
              <section key={label}>
                <div className="mb-3 flex items-center gap-2.5 px-1">
                  <svg className="h-3.5 w-3.5 text-ink-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                  <h2 className="micro-label !text-ink-300">{label}</h2>
                  <span className="rounded-full bg-white/[0.05] px-2 py-0.2 font-mono text-[10px] text-ink-400">
                    {items.length}
                  </span>
                  <div className="h-px flex-1 bg-gradient-to-r from-ink-500/20 via-ink-500/5 to-transparent" />
                </div>
                <div className={gridCls}>
                  {items.map((n) => (
                    <NoteCard
                      key={n.id}
                      note={n}
                      highlight={selectedId === n.id}
                      onOpen={onOpen}
                      onPin={onPin}
                      onTagClick={(t) => setTagFilter((cur) => (cur === t ? null : t))}
                      onToggleTask={handleToggleTask}
                      onRetry={handleRetry}
                      onDelete={handleDelete}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
