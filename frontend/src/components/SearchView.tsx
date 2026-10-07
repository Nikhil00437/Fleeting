import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { appColor } from "../apps";
import { fmtDuration, relTime } from "../time";
import NoteCard from "./NoteCard";
import { runNoteAction } from "./actionRunner";
import { bucketCounts, emptyUnified, sessionLabel } from "./unifiedSearch";
import {
  AUDIO_OP,
  DATE_PRESETS,
  activeDatePreset,
  applyDatePreset,
  hasOperator,
  toggleOperator,
} from "./searchQuery";
import {
  ClockIcon,
  LinkIcon,
  MicIcon,
  SearchIcon,
  SlidersIcon,
  SparkIcon,
  TextIcon,
  XIcon,
} from "./Icons";
import type { Note, QueryLogEntry, SearchMode, TagCount, TranscriptResult, UnifiedResult } from "../types";

interface Props {
  notes?: Note[];
  focusRef: React.RefObject<HTMLInputElement | null>;
  selectedId?: string | null;
  onOpen: (id: string) => void;
  /** #319: open a note and jump its audio player to t seconds. */
  onOpenAt?: (id: string, t: number) => void;
  onPin: (id: string) => void;
  onNoteUpdated?: (note: Note) => void;
  onNoteDeleted?: (id: string) => void;
  onToast?: (message: string, kind?: "ok" | "err") => void;
}

function isEmptyFailedVoice(n: Note): boolean {
  return (
    n.status === "failed" &&
    !n.title.trim() &&
    !n.raw_text.trim() &&
    !n.summary.trim()
  );
}

export default function SearchView({
  notes = [],
  focusRef,
  selectedId,
  onOpen,
  onOpenAt,
  onPin,
  onNoteUpdated,
  onNoteDeleted,
  onToast,
}: Props) {
  // These three were passed to NoteCard as bare async handlers with no catch,
  // so any failure became an unhandled rejection with nothing on screen.
  const toast = onToast ?? ((message: string) => void message);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [results, setResults] = useState<Note[] | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [searching, setSearching] = useState(false);
  const [scope, setScope] = useState<"notes" | "activity">("notes");
  const [unified, setUnified] = useState<UnifiedResult | null>(null);
  // #315: hybrid RRF keyword weight — surfaced as a slider, server clamps.
  const [alpha, setAlpha] = useState(0.5);
  // #317: hover/focus preview — the note shown in the side pane.
  const [previewId, setPreviewId] = useState<string | null>(null);
  // #49/#322: recent + most-searched queries for the empty-input dropdown.
  const [showSuggest, setShowSuggest] = useState(false);
  const [recentQueries, setRecentQueries] = useState<QueryLogEntry[]>([]);
  const [topQueries, setTopQueries] = useState<QueryLogEntry[]>([]);
  // #319: voice-transcript hits with audio timestamps.
  const [transcripts, setTranscripts] = useState<TranscriptResult[]>([]);
  const debounceRef = useRef<number>(0);

  useEffect(() => {
    api.tags().then(setTags).catch(() => {});
  }, [notes.length]);

  function loadHistory() {
    api
      .searchHistory()
      .then((h) => {
        setRecentQueries(h.recent);
        setTopQueries(h.top);
      })
      .catch(() => {});
  }

  // #321: toggle the "not relevant" mark, then re-rank server-side so the
  // demotion is visible without a manual refresh.
  async function handleFeedback(id: string) {
    const q = query.trim();
    if (!q) return;
    const note = (results ?? []).find((n) => n.id === id);
    if (!note) return;
    const down = !note.feedback_down;
    try {
      await api.searchFeedback(id, q, down);
      setResults(await api.search(q, { mode, alpha }));
      toast(down ? "Marked not relevant" : "Feedback removed");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    const q = query.trim();
    setPreviewId(null);
    if (!q) {
      setResults(null);
      setTranscripts([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    if (scope === "activity") {
      setUnified(null);
      setTranscripts([]);
    }
    debounceRef.current = window.setTimeout(async () => {
      try {
        if (scope === "activity") {
          setResults([]);
          setUnified(await api.unifiedSearch(q, { limit: 20 }));
        } else {
          const [hits, transcriptHits] = await Promise.all([
            api.search(q, { mode, alpha }),
            api.transcriptSearch(q).catch(() => [] as TranscriptResult[]),
          ]);
          setResults(hits);
          setTranscripts(transcriptHits);
        }
      } catch {
        if (scope === "activity") setUnified(emptyUnified() as UnifiedResult);
        else setResults([]);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => window.clearTimeout(debounceRef.current);
  }, [query, mode, scope, alpha]);

  const browseNotes = useMemo(
    () => notes.filter((n) => !isEmptyFailedVoice(n)),
    [notes],
  );

  const activeList = useMemo(() => {
    const base = query.trim() ? (results ?? []) : browseNotes;
    if (typeFilter === "all") return base;
    return base.filter((n) => n.type === typeFilter);
  }, [query, results, browseNotes, typeFilter]);

  const typeCounts = useMemo(() => {
    const base = query.trim() ? (results ?? []) : browseNotes;
    return {
      all: base.length,
      text: base.filter((n) => n.type === "text").length,
      voice: base.filter((n) => n.type === "voice").length,
      youtube: base.filter((n) => n.type === "youtube").length,
    };
  }, [query, results, browseNotes]);

  // #317: the note currently shown in the hover/focus preview pane.
  const previewNote = useMemo(
    () => (previewId ? (activeList.find((n) => n.id === previewId) ?? null) : null),
    [activeList, previewId],
  );

  // #49: complete a half-typed tag: operator from the known tag list.
  const tagCompletions = useMemo(() => {
    const m = query.match(/(?:^|\s)tag:(\S*)$/i);
    if (!m) return [];
    const needle = m[1].replace(/^#/, "").toLowerCase();
    return tags.filter((t) => t.tag.toLowerCase().includes(needle)).slice(0, 6);
  }, [query, tags]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Docked Pane Search & Filter Toolbar */}
      <div className="app-toolbar flex h-12 shrink-0 items-center gap-3 px-5">
        <div className="relative min-w-0 flex-1 max-w-xl">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-ember-400" />
          <input
            ref={focusRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => {
              setShowSuggest(true);
              loadHistory();
            }}
            onBlur={() => setShowSuggest(false)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setShowSuggest(false);
            }}
            placeholder="Search across titles, transcripts, summaries, and #tags…"
            spellCheck={false}
            aria-label="Search query"
            className="h-8 w-full rounded-xl border border-ink-800/90 bg-ink-950/90 pr-8 pl-9 text-xs text-ink-100 placeholder-ink-400 outline-none transition-colors focus:border-ember-500/50"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute top-1/2 right-2.5 -translate-y-1/2 rounded p-0.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
            >
              <XIcon className="h-3 w-3" />
            </button>
          )}

          {/* #49 recent searches on empty focus, tag completions while typing */}
          {showSuggest && tagCompletions.length > 0 && (
            <ul
              className="absolute top-full z-30 mt-1 w-full overflow-hidden rounded-xl border border-ink-800 bg-ink-950/95 py-1 shadow-xl backdrop-blur"
              onMouseDown={(e) => e.preventDefault()}
            >
              {tagCompletions.map(({ tag, count }) => (
                <li key={tag}>
                  <button
                    onMouseDown={() => {
                      setQuery(query.replace(/tag:\S*$/i, `tag:${tag}`));
                      setShowSuggest(false);
                    }}
                    className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800/80"
                  >
                    <span className="font-mono text-ember-300">#{tag}</span>
                    <span className="font-mono text-[10px] text-ink-500">{count}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {showSuggest && !query.trim() && (recentQueries.length > 0 || topQueries.length > 0) && (
            <div
              className="absolute top-full z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-ink-800 bg-ink-950/95 py-1 shadow-xl backdrop-blur"
              onMouseDown={(e) => e.preventDefault()}
            >
              {recentQueries.length > 0 && (
                <>
                  <p className="micro-label px-3 pt-1.5 pb-1">Recent searches</p>
                  {recentQueries.map((entry) => (
                    <button
                      key={`recent-${entry.q}`}
                      onMouseDown={() => {
                        setQuery(entry.q);
                        setShowSuggest(false);
                      }}
                      className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800/80"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono">{entry.q}</span>
                      <span className="shrink-0 font-mono text-[10px] text-ink-500">
                        {entry.hits} hits
                      </span>
                    </button>
                  ))}
                </>
              )}
              {topQueries.length > 0 && (
                <>
                  <p className="micro-label px-3 pt-2 pb-1">Most searched</p>
                  {topQueries.map((entry) => (
                    <button
                      key={`top-${entry.q}`}
                      onMouseDown={() => {
                        setQuery(entry.q);
                        setShowSuggest(false);
                      }}
                      className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs text-ink-200 hover:bg-ink-800/80"
                    >
                      <span className="min-w-0 flex-1 truncate font-mono">{entry.q}</span>
                      <span className="shrink-0 font-mono text-[10px] text-ink-500">
                        {entry.searched}×
                      </span>
                    </button>
                  ))}
                </>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1 rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {[
            { id: "all", label: "All", count: typeCounts.all, icon: null },
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
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition-all ${
                typeFilter === tab.id
                  ? "bg-ink-800 font-semibold text-ink-100 shadow-xs"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
              <span className="font-mono text-[10px] text-ink-500">{tab.count}</span>
            </button>
          ))}
        </div>

        {/* Search Mode Toggles: Hybrid | Keyword | Semantic */}
        <div className="flex items-center gap-1 rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {(["hybrid", "keyword", "semantic"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs capitalize transition-all ${
                mode === m
                  ? "bg-ink-800 font-semibold text-ember-300 shadow-xs ring-1 ring-ember-400/25"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {m === "hybrid" && <SparkIcon className="h-3 w-3 text-ember-400" />}
              <span>{m}</span>
            </button>
          ))}
        </div>

        <span className="ml-auto hidden rounded-lg border border-ink-800/80 bg-ink-950/60 px-2.5 py-1 font-mono text-[10.5px] text-ink-400 md:inline">
          {mode === "hybrid"
            ? "Hybrid RRF (FTS5 + Vector Cosine)"
            : mode === "semantic"
              ? "Dense Vector Cosine Similarity"
              : "SQLite FTS5 · BM25 Ranking"}
        </span>
      </div>

      {/* #41 Filter chips — date presets and audio; each chip just edits the
          operator query, so chips and typed operators stay one grammar. */}
      <div className="flex h-9 shrink-0 items-center gap-2 border-b border-ink-800/60 px-5">
        <span className="micro-label flex items-center gap-1.5">
          <ClockIcon className="h-3 w-3 text-ember-400" /> When
        </span>
        <div className="flex items-center gap-1">
          {DATE_PRESETS.map((preset) => {
            const active =
              preset.days === null
                ? activeDatePreset(query) === "any"
                : activeDatePreset(query) === preset.id;
            return (
              <button
                key={preset.id}
                onClick={() => setQuery(applyDatePreset(query, preset))}
                aria-pressed={active}
                className={`rounded-lg px-2 py-0.5 text-[11px] transition-all ${
                  active
                    ? "bg-ink-800 font-semibold text-ink-100 shadow-xs"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                {preset.label}
              </button>
            );
          })}
        </div>
        <span className="mx-1 h-4 w-px bg-ink-800" aria-hidden="true" />
        <button
          onClick={() => setQuery(toggleOperator(query, AUDIO_OP))}
          aria-pressed={hasOperator(query, AUDIO_OP)}
          className={`flex items-center gap-1 rounded-lg px-2 py-0.5 text-[11px] transition-all ${
            hasOperator(query, AUDIO_OP)
              ? "bg-iris-500/20 font-semibold text-iris-200 ring-1 ring-iris-400/30"
              : "text-ink-400 hover:text-ink-200"
          }`}
        >
          <MicIcon className="h-3 w-3" /> Has audio
        </button>

        {/* #315 weighting slider — only meaningful in hybrid mode */}
        {mode === "hybrid" && (
          <div className="ml-auto flex items-center gap-2" title="Keyword vs. semantic weighting (α)">
            <SlidersIcon className="h-3 w-3 text-ink-400" />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={alpha}
              onChange={(e) => setAlpha(Number(e.target.value))}
              aria-label="Hybrid keyword weight"
              className="h-1 w-24 cursor-pointer appearance-none rounded-full bg-ink-800 accent-ember-400"
            />
            <span className="w-10 font-mono text-[10.5px] tabular-nums text-ink-300">
              α {alpha.toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {/* Scrollable Knowledge Explorer Viewport */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {/* Topic & Tag Facet Matrix */}
        {tags.length > 0 && (
          <div className="glass-studio rounded-2xl p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <SparkIcon className="h-3.5 w-3.5 text-ember-400" />
                <h2 className="micro-label">Topic & Tag Index — Click any tag to filter</h2>
              </div>
              <div className="flex items-center gap-2.5">
                {query.trim() && (
                  <button
                    onClick={() => setQuery("")}
                    className="rounded-md border border-ember-500/30 bg-ember-500/10 px-2 py-0.5 font-mono text-[10px] font-medium text-ember-300 hover:bg-ember-500/20"
                  >
                    Clear filter ({query}) ×
                  </button>
                )}
                <span className="font-mono text-[11px] text-ink-400">
                  {tags.length} topics across {browseNotes.length} captures
                </span>
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {tags.slice(0, 24).map(({ tag, count }) => {
                const color = appColor(tag);
                // #313: tag chips now toggle the tag: operator, not bare text,
                // so chips and hand-typed operators stay one grammar.
                const tagOp = `tag:${tag}`;
                const isSelected = hasOperator(query, tagOp);
                return (
                  <button
                    key={tag}
                    onClick={() => setQuery(toggleOperator(query, tagOp))}
                    className={`group flex items-center gap-2 rounded-xl border px-3 py-1.5 text-xs transition-all ${
                      isSelected
                        ? "border-ember-400/60 bg-ember-500/15 text-ink-100 shadow-sm"
                        : "border-ink-800/90 bg-ink-950/65 text-ink-200 hover:border-ink-700 hover:bg-ink-900"
                    }`}
                  >
                    <span
                      className="h-2 w-2 shrink-0 rounded-full"
                      style={{ background: color, boxShadow: `0 0 8px ${color}66` }}
                    />
                    <span
                      className={`font-mono text-[11.5px] font-medium ${
                        isSelected ? "text-ember-200" : "text-ink-100 group-hover:text-ember-300"
                      }`}
                    >
                      #{tag}
                    </span>
                    <span className="rounded-md bg-ink-900/90 px-1.5 py-0.2 font-mono text-[10px] text-ink-400">
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Activity-aware results: window sessions + commits */}
        {scope === "activity" && unified ? (
          <div className="space-y-3">
            {bucketCounts(unified).map((b) => (
              <div key={b.key}>
                <p className="micro-label mb-1.5 px-1">
                  {b.label} · {b.count}
                </p>
                {b.count === 0 ? (
                  <p className="px-1 text-[11px] text-ink-500">No {b.label.toLowerCase()} matched.</p>
                ) : b.key === "sessions" ? (
                  <ul className="space-y-1">
                    {unified.sessions.map((s) => (
                      <li
                        key={s.id}
                        className="rise flex items-center gap-2 rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-1.5 text-xs text-ink-200"
                      >
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: appColor(s.app_class) }}
                          aria-hidden="true"
                        />
                        <span className="min-w-0 flex-1 truncate">{sessionLabel(s)}</span>
                        <span className="shrink-0 font-mono text-[10px] text-ink-500">{s.day}</span>
                      </li>
                    ))}
                  </ul>
                ) : b.key === "commits" ? (
                  <ul className="space-y-1">
                    {unified.commits.map((c) => (
                      <li
                        key={`${c.repo}:${c.committed_at}:${c.subject}`}
                        className="flex items-center gap-2 rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-1.5 text-xs text-ink-200"
                      >
                        <span className="shrink-0 font-mono text-[10px] text-cyan-400">{c.repo}</span>
                        <span className="min-w-0 flex-1 truncate">{c.subject}</span>
                        <span className="shrink-0 font-mono text-[10px] text-ink-500">
                          {c.committed_at.slice(0, 10)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {/* Knowledge Base Results / Stream */}
        <div className={scope === "activity" ? "hidden" : "space-y-3"}>
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <span className="micro-label">
                {query.trim()
                  ? searching
                    ? `Searching ${mode} index…`
                    : `Search Results for "${query}" (${mode})`
                  : "Indexed Knowledge Base"}
              </span>
              <span className="rounded-md border border-ink-800 bg-ink-900/80 px-2 py-0.5 font-mono text-[10.5px] text-ink-300">
                {activeList.length} {activeList.length === 1 ? "capture" : "captures"}
              </span>
              <div className="flex items-center gap-0.5 rounded-lg border border-ink-800 bg-ink-900/80 p-0.5">
                {(["notes", "activity"] as const).map((sc) => (
                  <button
                    key={sc}
                    onClick={() => setScope(sc)}
                    aria-pressed={scope === sc}
                    className={`rounded-md px-2 py-0.5 font-mono text-[10.5px] ${
                      scope === sc
                        ? "bg-ember-500/25 font-semibold text-ember-300"
                        : "text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    {sc === "notes" ? "Notes" : "What I did"}
                  </button>
                ))}
              </div>
            </div>
            {query.trim() && (
              <button
                onClick={() => setQuery("")}
                className="text-xs text-ink-400 hover:text-ember-300"
              >
                Reset search
              </button>
            )}
          </div>

          {/* #319 transcript hits — timestamped matches inside voice notes */}
          {transcripts.length > 0 && (
            <div className="glass-studio rounded-2xl p-3.5">
              <p className="micro-label mb-2 !text-[9.5px]">From your voice memos</p>
              <ul className="space-y-1">
                {transcripts.map((tr) => (
                  <li key={tr.note.id}>
                    <button
                      onClick={() => onOpenAt?.(tr.note.id, tr.hits[0]?.t ?? 0)}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left hover:bg-white/[0.04]"
                    >
                      <span className="shrink-0 font-mono text-[10px] text-ember-300">
                        {fmtDuration(tr.hits[0]?.t ?? 0)}
                      </span>
                      <span className="truncate text-xs text-ink-200">{tr.hits[0]?.text}</span>
                    </button>
                    {tr.hits.slice(1).map((h, i) => (
                      <button
                        key={i}
                        onClick={() => onOpenAt?.(tr.note.id, h.t)}
                        className="flex w-full items-center gap-2 rounded-lg px-2 py-0.5 pl-12 text-left hover:bg-white/[0.04]"
                      >
                        <span className="shrink-0 font-mono text-[10px] text-ink-500">{fmtDuration(h.t)}</span>
                        <span className="truncate text-[11px] text-ink-400">{h.text}</span>
                      </button>
                    ))}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeList.length === 0 ? (
            <div className="glass-studio flex flex-col items-center justify-center rounded-2xl py-16 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-400/30">
                <SearchIcon className="h-5 w-5" />
              </div>
              <h3 className="mt-3 text-sm font-semibold text-ink-100">
                No matching captures found
              </h3>
              <p className="mt-1 max-w-sm text-xs text-ink-400">
                Try another keyword, select a different media tab, or click one of the topic tags above.
              </p>
            </div>
          ) : (
            <div className="flex items-start gap-4">
              <div
                className={`grid min-w-0 flex-1 grid-cols-1 gap-3 ${
                  selectedId || previewNote ? "xl:grid-cols-2" : "md:grid-cols-2"
                }`}
              >
                {activeList.map((n) => (
                  <div
                    key={n.id}
                    onMouseEnter={() => setPreviewId(n.id)}
                    onFocus={() => setPreviewId(n.id)}
                  >
                    <NoteCard
                      note={n}
                      highlight={selectedId === n.id}
                      onOpen={onOpen}
                      onPin={onPin}
                      onFeedback={query.trim() ? handleFeedback : undefined}
                      feedbackDown={n.feedback_down}
                      onTagClick={(t) => setQuery(toggleOperator(query, `tag:${t}`))}
                      onToggleTask={(note, itemId) =>
                        runNoteAction({
                          api,
                          toast,
                          action: () =>
                            api.updateNote(note.id, {
                              action_items: note.action_items.map((it) =>
                                it.id === itemId ? { ...it, done: !it.done } : it,
                              ),
                            } as never),
                          success: "Task updated",
                          onDone: (updated) => onNoteUpdated?.(updated),
                        })
                      }
                      onRetry={(id) =>
                        runNoteAction({
                          api,
                          toast,
                          action: () => api.reprocess(id),
                          success: "Reprocessing started",
                          onDone: (updated) => onNoteUpdated?.(updated),
                        })
                      }
                      onDelete={(id) =>
                        runNoteAction({
                          api,
                          toast,
                          action: () => api.deleteNote(id),
                          success: "Note deleted",
                          onDone: () => onNoteDeleted?.(id),
                        })
                      }
                    />
                  </div>
                ))}
              </div>

              {/* #317 search-as-you-type preview pane — glance without
                  leaving the results; hover or keyboard-focus drives it */}
              {previewNote && scope === "notes" && (
                <aside
                  aria-label="Result preview"
                  className="glass-studio sticky top-0 hidden w-80 shrink-0 self-start rounded-2xl p-4 xl:block"
                >
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="micro-label">Preview</span>
                    <button
                      onClick={() => setPreviewId(null)}
                      className="rounded p-0.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
                      aria-label="Close preview"
                    >
                      <XIcon className="h-3 w-3" />
                    </button>
                  </div>
                  <h3 className="line-clamp-2 text-sm font-semibold tracking-tight text-ink-100">
                    {previewNote.title || "Untitled capture"}
                  </h3>
                  <p className="mt-0.5 font-mono text-[10.5px] text-ink-400">
                    {relTime(previewNote.created_at)}
                    {" · "}
                    {previewNote.type}
                  </p>
                  {(previewNote.summary || previewNote.raw_text) && (
                    <p className="mt-2 line-clamp-[10] text-xs leading-relaxed text-ink-200">
                      {previewNote.summary || previewNote.raw_text.slice(0, 420)}
                    </p>
                  )}
                  {previewNote.tags.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {previewNote.tags.slice(0, 8).map((t) => (
                        <button
                          key={t}
                          onClick={() => setQuery(toggleOperator(query, `tag:${t}`))}
                          className="rounded-md border border-white/[0.06] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] text-ink-300 hover:border-ember-400/40 hover:text-ember-200"
                        >
                          #{t}
                        </button>
                      ))}
                    </div>
                  )}
                  <button
                    onClick={() => onOpen(previewNote.id)}
                    className="mt-3 w-full rounded-lg border border-ember-500/30 bg-ember-500/10 px-2 py-1.5 text-[11px] font-semibold text-ember-300 transition-colors hover:bg-ember-500/20"
                  >
                    Open note
                  </button>
                </aside>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
