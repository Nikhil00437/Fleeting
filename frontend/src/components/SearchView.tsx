import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { appColor } from "../apps";
import NoteCard from "./NoteCard";
import { LinkIcon, MicIcon, SearchIcon, SparkIcon, TextIcon, XIcon } from "./Icons";
import type { Note, TagCount } from "../types";

interface Props {
  notes?: Note[];
  focusRef: React.RefObject<HTMLInputElement | null>;
  selectedId?: string | null;
  onOpen: (id: string) => void;
  onPin: (id: string) => void;
  onNoteUpdated?: (note: Note) => void;
  onNoteDeleted?: (id: string) => void;
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
}: Props) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [results, setResults] = useState<Note[] | null>(null);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [searching, setSearching] = useState(false);
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
    debounceRef.current = window.setTimeout(async () => {
      try {
        setResults(await api.search(q));
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 180);
    return () => window.clearTimeout(debounceRef.current);
  }, [query]);

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

        <span className="ml-auto hidden rounded-lg border border-ink-800/80 bg-ink-950/60 px-2.5 py-1 font-mono text-[10.5px] text-ink-400 md:inline">
          SQLite FTS5 · BM25 Ranking
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

        {/* Knowledge Base Results / Stream */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <span className="micro-label">
                {query.trim()
                  ? searching
                    ? "Searching FTS5 index…"
                    : `Search Results for "${query}"`
                  : "Indexed Knowledge Base"}
              </span>
              <span className="rounded-md border border-ink-800 bg-ink-900/80 px-2 py-0.5 font-mono text-[10.5px] text-ink-300">
                {activeList.length} {activeList.length === 1 ? "capture" : "captures"}
              </span>
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
                  onToggleTask={async (note, itemId) => {
                    const items = note.action_items.map((it) =>
                      it.id === itemId ? { ...it, done: !it.done } : it,
                    );
                    const updated = await api.updateNote(note.id, { action_items: items } as never);
                    onNoteUpdated?.(updated);
                  }}
                  onRetry={async (id) => {
                    const updated = await api.reprocess(id);
                    onNoteUpdated?.(updated);
                  }}
                  onDelete={async (id) => {
                    await api.deleteNote(id);
                    onNoteDeleted?.(id);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
