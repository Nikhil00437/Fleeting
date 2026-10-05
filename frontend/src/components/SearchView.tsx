import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { appColor } from "../apps";
import NoteCard from "./NoteCard";
import { runNoteAction } from "./actionRunner";
import { bucketCounts, emptyUnified, sessionLabel } from "./unifiedSearch";
import { LinkIcon, MicIcon, SearchIcon, SparkIcon, TextIcon, XIcon } from "./Icons";
import type { Note, SearchMode, TagCount, UnifiedResult } from "../types";

interface Props {
  notes?: Note[];
  focusRef: React.RefObject<HTMLInputElement | null>;
  selectedId?: string | null;
  onOpen: (id: string) => void;
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
  const debounceRef = useRef<number>(0);

  useEffect(() => {
    api.tags().then(setTags).catch(() => {});
  }, [notes.length]);

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    const q = query.trim();
    if (!q) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    if (scope === "activity") setUnified(null);
    debounceRef.current = window.setTimeout(async () => {
      try {
        if (scope === "activity") {
          setResults([]);
          setUnified(await api.unifiedSearch(q, { limit: 20 }));
        } else {
          setResults(await api.search(q, { mode }));
        }
      } catch {
        if (scope === "activity") setUnified(emptyUnified() as UnifiedResult);
        else setResults([]);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => window.clearTimeout(debounceRef.current);
  }, [query, mode, scope]);

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
            placeholder="Search across titles, transcripts, summaries, and #tags…"
            spellCheck={false}
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
                const isSelected = query.trim().toLowerCase() === tag.toLowerCase();
                return (
                  <button
                    key={tag}
                    onClick={() => setQuery(isSelected ? "" : tag)}
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
                        className="flex items-center gap-2 rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-1.5 text-xs text-ink-200"
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
            <div
              className={`grid grid-cols-1 gap-3 ${
                selectedId ? "xl:grid-cols-2" : "md:grid-cols-2"
              }`}
            >
              {activeList.map((n) => (
                <NoteCard
                  key={n.id}
                  note={n}
                  highlight={selectedId === n.id}
                  onOpen={onOpen}
                  onPin={onPin}
                  onTagClick={(t) => setQuery(t)}
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
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
