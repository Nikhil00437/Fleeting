import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { dayGroup } from "../time";
import { AreaTrend, Bars, Ring, StackBar } from "./charts";
import NoteCard from "./NoteCard";
import { runNoteAction } from "./actionRunner";
import { buildTagTree, flattenTagTree, tagMatches } from "./tagTree";
import { relTime } from "../time";
import { activationProps } from "./a11y";
import {
  ActivityIcon,
  CheckIcon,
  FilterIcon,
  FolderIcon,
  GridIcon,
  LinkIcon,
  ListIcon,
  MicIcon,
  PinIcon,
  SearchIcon,
  ShieldIcon,
  SparkIcon,
  StarIcon,
  TextIcon,
  TrashIcon,
  XIcon,
} from "./Icons";
import type { Collection, Note, Stats, TagCount } from "../types";

interface Props {
  refreshNotes?: () => void;
  notes: Note[];
  selectedId?: string | null;
  onOpen: (id: string) => void;
  onPin: (id: string) => void;
  onStar?: (id: string) => void;
  onQuickStart: () => void;
  /** Bumped by collections.changed SSE events; triggers a refetch. */
  collectionsKey?: number;
  onNoteUpdated?: (note: Note) => void;
  onNoteDeleted?: (id: string) => void;
  onToast?: (message: string, kind?: "ok" | "err") => void;
}

type Suggestion = {
  kind: "archive" | "add_tag" | "rename" | "merge";
  note_id: string;
  title: string;
  reason: string;
  value?: string;
  extra_note_ids?: string[];
};

function dayLabel(d: string, total: number) {
  const dt = new Date(d + "T12:00:00");
  if (total <= 7) return dt.toLocaleDateString([], { weekday: "short" });
  return `${dt.getMonth() + 1}/${dt.getDate()}`;
}

export default function Inbox({
  refreshNotes,
  notes,
  selectedId,
  onOpen,
  onPin,
  onStar,
  onQuickStart,
  collectionsKey,
  onNoteUpdated,
  onNoteDeleted,
  onToast,
}: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [rangeDays, setRangeDays] = useState<7 | 14 | 30>(7);
  const [chartMode, setChartMode] = useState<"bars" | "area">("bars");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  // #273: dedicated starred view — a filter over the same feed, not a fetch.
  const [starredOnly, setStarredOnly] = useState(false);
  // #305: Alt-clicked tag — everything carrying it is hidden until cleared.
  const [excludedTag, setExcludedTag] = useState<string | null>(null);
  // #270: tag tree panel.
  const [showTagTree, setShowTagTree] = useState(false);
  const [tagCounts, setTagCounts] = useState<TagCount[] | null>(null);
  // #271: triage — one note at a time, a decision before the next appears.
  const [triageOpen, setTriageOpen] = useState(false);
  const [triageDone, setTriageDone] = useState<Set<string>>(new Set());
  // #421: monthly cleanup assistant.
  const [showCleanup, setShowCleanup] = useState(false);
  const [cleanupSuggestions, setCleanupSuggestions] = useState<Suggestion[] | null>(null);
  // #424: review queue — notes whose enrichment used the heuristic fallback.
  const [reviewOnly, setReviewOnly] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [showMetrics, setShowMetrics] = useState(true);
  const [showFailed, setShowFailed] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  // #274: trash panel with lazy fetch — only hits /api/trash once opened.
  const [showTrash, setShowTrash] = useState(false);
  const [trashNotes, setTrashNotes] = useState<Note[] | null>(null);
  const [trashLoading, setTrashLoading] = useState(false);
  // #267/#268/#269: collections dropdown + open collection view.
  const [showCollections, setShowCollections] = useState(false);
  const [collections, setCollections] = useState<Collection[] | null>(null);
  const [activeCollection, setActiveCollection] = useState<(Collection & { notes: Note[] }) | null>(null);
  // #272: filing rules live beside collections — both are "where notes go".
  const [rules, setRules] = useState<Awaited<ReturnType<typeof api.filingRules>> | null>(null);
  const [ruleForm, setRuleForm] = useState({ field: "tag", value: "", action: "add_tag", actionValue: "" });
  const togglePick = (id: string) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function bulkAction(kind: "pin" | "archive" | "delete") {
    const ids = [...picked];
    if (ids.length === 0) return;
    let ok = 0;
    for (const id of ids) {
      try {
        if (kind === "pin") onPin(id);
        else if (kind === "archive") {
          const n = await api.archiveNote(id);
          onNoteUpdated?.(n);
        } else {
          await api.deleteNote(id);
          onNoteDeleted?.(id);
        }
        ok++;
      } catch (e) {
        toast(e instanceof Error ? e.message : String(e), "err");
      }
    }
    setPicked(new Set());
    setSelectMode(false);
    toast(`${kind === "delete" ? "Trashed" : kind === "archive" ? "Archived" : "Pinned"} ${ok} note${ok === 1 ? "" : "s"}`);
    void refreshStats();
  }

  // Every mutation below used to swallow its error, so a failed delete left the
  // note on screen with no explanation. Toast the outcome instead.
  const toast = onToast ?? ((message: string) => void message);
  const refreshStats = useCallback(
    () => api.stats(rangeDays).then(setStats).catch(() => {}),
    [rangeDays],
  );

  function loadCleanup() {
    api.cleanupSuggestions().then(setCleanupSuggestions).catch(() => setCleanupSuggestions([]));
  }

  async function applySuggestion(s: Suggestion) {
    if (s.kind !== "archive" && s.kind !== "add_tag") return;
    try {
      await api.applyCleanup(s.note_id, s.kind, s.value);
      setCleanupSuggestions((list) => (list ?? []).filter((x) => !(x.note_id === s.note_id && x.kind === s.kind)));
      toast(s.kind === "archive" ? "Note archived" : `Tagged #${s.value}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  function loadTagCounts() {
    api.tags().then(setTagCounts).catch(() => setTagCounts([]));
  }

  function loadCollections() {
    api.collections().then(setCollections).catch(() => setCollections([]));
    api.filingRules().then(setRules).catch(() => setRules([]));
  }

  async function addRule() {
    if (!ruleForm.value.trim()) return;
    try {
      await api.createFilingRule({
        match_field: ruleForm.field,
        match_value: ruleForm.value.trim(),
        action: ruleForm.action,
        action_value: ruleForm.actionValue.trim() || null,
      });
      setRuleForm({ field: "tag", value: "", action: "add_tag", actionValue: "" });
      api.filingRules().then(setRules).catch(() => {});
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function runRules() {
    try {
      const r = await api.runFilingRules();
      toast(`Rules applied to ${r.changed} note${r.changed === 1 ? "" : "s"}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function deleteRule(id: number) {
    try {
      await api.deleteFilingRule(id);
      api.filingRules().then(setRules).catch(() => {});
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  // Refetch whenever a collections.changed SSE lands while the dropdown is open,
  // and refresh an open collection's notes so membership stays truthful.
  useEffect(() => {
    if (showCollections) loadCollections();
    if (activeCollection) {
      api
        .collection(activeCollection.id)
        .then(setActiveCollection)
        .catch(() => setActiveCollection(null));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionsKey]);

  async function openCollection(id: string) {
    try {
      const detail = await api.collection(id);
      setActiveCollection(detail);
      setShowCollections(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function saveCurrentFilters() {
    const name =
      tagFilter ||
      (typeFilter !== "all" ? `${typeFilter} captures` : filterQuery.trim()) ||
      `Saved ${new Date().toLocaleDateString()}`;
    try {
      await api.createCollection({
        name,
        kind: "saved_query",
        query: {
          text: filterQuery.trim() || undefined,
          tag: tagFilter ?? undefined,
          type: typeFilter !== "all" ? typeFilter : undefined,
        },
      });
      toast(`Saved "${name}" as a collection`);
      loadCollections();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function deleteCollection(id: string) {
    try {
      await api.deleteCollection(id);
      if (activeCollection?.id === id) setActiveCollection(null);
      loadCollections();
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  function loadTrash() {
    setTrashLoading(true);
    api
      .trash()
      .then(setTrashNotes)
      .catch((e) => toast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => setTrashLoading(false));
  }

  async function handleRestore(id: string) {
    await runNoteAction({
      api,
      toast,
      action: () => api.restoreNote(id),
      success: "Note restored",
      onDone: (restored) => {
        setTrashNotes((list) => (list ?? []).filter((n) => n.id !== id));
        onNoteUpdated?.(restored);
        void refreshStats();
      },
    });
  }

  async function handlePurge(id: string) {
    await runNoteAction({
      api,
      toast,
      action: () => api.purgeNote(id),
      success: "Note permanently deleted",
      onDone: () => {
        setTrashNotes((list) => (list ?? []).filter((n) => n.id !== id));
        void refreshStats();
      },
    });
  }

  async function handleEmptyTrash() {
    await runNoteAction({
      api,
      toast,
      action: () => api.emptyTrash(),
      success: "Trash emptied",
      onDone: () => setTrashNotes([]),
    });
  }

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
      success: "Note moved to trash",
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

  // #274: trashed notes leave the inbox immediately; they live in /api/trash.
  const activeNotes = useMemo(
    () => notes.filter((n) => !n.archived && !n.trashed_at),
    [notes],
  );

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
      if (starredOnly && !n.starred) return false;
      if (reviewOnly && n.review_state !== "raw") return false;
      if (typeFilter !== "all" && n.type !== typeFilter) return false;
      // #270: a selected parent tag covers its descendants (work -> work/x).
      if (tagFilter && !n.tags.some((t) => tagMatches(t, tagFilter))) return false;
      if (excludedTag && n.tags.some((t) => tagMatches(t, excludedTag))) return false;
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
  }, [activeNotes, healthyNotes, showFailed, starredOnly, reviewOnly, excludedTag, typeFilter, tagFilter, filterQuery]);

  const pinned = filteredNotes.filter((n) => n.pinned);
  const rest = filteredNotes.filter((n) => !n.pinned);

  const groups: Array<[string, Note[]]> = [];
  for (const note of rest) {
    const label = dayGroup(note.created_at);
    const last = groups[groups.length - 1];
    if (last && last[0] === label) last[1].push(note);
    else groups.push([label, [note]]);
  }

  const reviewQueueCount = useMemo(
    () => healthyNotes.filter((n) => n.review_state === "raw").length,
    [healthyNotes],
  );

  // #271: oldest-first queue of anything not yet human-reviewed.
  const triageQueue = useMemo(
    () =>
      healthyNotes
        .filter((n) => n.review_state === "raw" || n.review_state === "enriched")
        .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [healthyNotes],
  );
  const triageCurrent = triageQueue.find((n) => !triageDone.has(n.id)) ?? null;

  function markTriageDone(id: string) {
    setTriageDone((s) => new Set(s).add(id));
  }

  async function triageKeep(note: Note) {
    markTriageDone(note.id);
    try {
      onNoteUpdated?.(await api.updateNote(note.id, { review_state: "reviewed" }));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function triageArchive(note: Note) {
    markTriageDone(note.id);
    try {
      onNoteUpdated?.(await api.archiveNote(note.id));
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function triageTrash(note: Note) {
    markTriageDone(note.id);
    try {
      await api.deleteNote(note.id);
      onNoteDeleted?.(note.id);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
    }
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

        {excludedTag && (
          <button
            onClick={() => setExcludedTag(null)}
            className="flex items-center gap-1 rounded-md border border-red-400/40 bg-red-500/10 px-2 py-1 text-xs font-medium text-red-200 hover:bg-red-500/20"
            title="Stop excluding this tag"
          >
            −#{excludedTag}
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
          <button
            onClick={() => setStarredOnly((v) => !v)}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              starredOnly
                ? "border-amber-400/40 bg-amber-500/15 text-amber-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Show starred notes only"
          >
            <StarIcon filled={starredOnly} className="h-3 w-3" />
          </button>

          {triageQueue.length > 0 && (
            <button
              onClick={() => {
                setTriageOpen((v) => !v);
                setTriageDone(new Set());
              }}
              className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
                triageOpen
                  ? "border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                  : "border-cyan-400/20 bg-ink-950/80 text-cyan-300/80 hover:text-cyan-200"
              }`}
              title="#271 File every unreviewed note, one at a time"
            >
              Triage
              <span className="font-mono">{triageQueue.length}</span>
            </button>
          )}

          <button
            onClick={() => {
              const next = !showTagTree;
              setShowTagTree(next);
              if (next) loadTagCounts();
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              showTagTree
                ? "border-emerald-400/35 bg-emerald-500/15 text-emerald-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Browse tags (nested tags show as a tree)"
          >
            <FilterIcon className="h-3 w-3" />
            <span className="hidden lg:inline">Tags</span>
          </button>

          {reviewQueueCount > 0 && (
            <button
              onClick={() => setReviewOnly((v) => !v)}
              className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
                reviewOnly
                  ? "border-amber-400/40 bg-amber-500/15 text-amber-200"
                  : "border-amber-400/20 bg-ink-950/80 text-amber-300/80 hover:text-amber-200"
              }`}
              title="Show notes enriched offline that need review"
            >
              <ShieldIcon className="h-3 w-3" />
              <span className="font-mono">{reviewQueueCount}</span>
            </button>
          )}

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

          <button
            onClick={() => {
              const next = !showCollections;
              setShowCollections(next);
              if (next) loadCollections();
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              showCollections || activeCollection
                ? "border-iris-400/35 bg-iris-500/15 text-iris-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Collections — projects, playlists and saved searches"
          >
            <FolderIcon className="h-3 w-3" />
            <span className="hidden lg:inline">Collections</span>
          </button>

          <button
            onClick={() => {
              const next = !showTrash;
              setShowTrash(next);
              if (next) loadTrash();
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              showTrash
                ? "border-red-400/35 bg-red-500/15 text-red-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Open trash — notes are kept here before auto-purge"
          >
            <TrashIcon className="h-3 w-3" />
            <span className="hidden lg:inline">Trash</span>
          </button>

          <button
            onClick={() => {
              const next = !showCleanup;
              setShowCleanup(next);
              if (next) loadCleanup();
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              showCleanup
                ? "border-violet-400/40 bg-violet-500/15 text-violet-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Cleanup suggestions — archive, tag, rename, merge"
          >
            <SparkIcon className="h-3 w-3" />
            <span className="hidden lg:inline">Cleanup</span>
          </button>

          <button
            onClick={() => {
              setSelectMode((v) => !v);
              setPicked(new Set());
            }}
            className={`flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-colors ${
              selectMode
                ? "border-ember-400/35 bg-ember-500/15 text-ember-200"
                : "border-white/[0.07] bg-ink-950/80 text-ink-400 hover:text-ink-200"
            }`}
            title="Select multiple notes"
          >
            Select
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

      {/* #272 Filing rules section (inside the Collections panel) */}
      {showCollections && (
        <div className="relative z-20 shrink-0 border-b border-ink-800 bg-ink-950/95 px-4 pb-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="micro-label">Auto-filing rules — applied to new captures</p>
            <button
              onClick={() => void runRules()}
              className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:text-ink-100"
              title="Apply all enabled rules to existing notes"
            >
              Run on existing notes
            </button>
          </div>
          {rules && rules.length > 0 && (
            <div className="mb-2 space-y-1">
              {rules.map((r) => (
                <div key={r.id} className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-1 text-[11px]">
                  <span className="font-mono text-ink-300">
                    {r.match_field}:{r.match_value}
                  </span>
                  <span className="text-ink-600">→</span>
                  <span className="font-mono text-ink-300">
                    {r.action}
                    {r.action_value ? `:${r.action_value}` : ""}
                  </span>
                  {!r.enabled && <span className="text-ink-600">(off)</span>}
                  <button
                    onClick={() => void deleteRule(r.id)}
                    className="ml-auto text-ink-500 hover:text-red-300"
                    aria-label={`Delete rule ${r.match_field}:${r.match_value}`}
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              value={ruleForm.field}
              onChange={(e) => setRuleForm((f) => ({ ...f, field: e.target.value }))}
              className="rounded-lg border border-white/[0.08] bg-ink-950 px-2 py-1 text-[11px] text-ink-200 outline-none"
              aria-label="Rule match field"
            >
              <option value="tag">tag</option>
              <option value="type">type</option>
              <option value="title">title contains</option>
            </select>
            <input
              value={ruleForm.value}
              onChange={(e) => setRuleForm((f) => ({ ...f, value: e.target.value }))}
              placeholder={ruleForm.field === "type" ? "voice" : "cooking"}
              className="h-7 w-28 rounded-lg border border-white/[0.08] bg-ink-950 px-2 text-[11px] text-ink-200 placeholder-ink-500 outline-none"
              aria-label="Rule match value"
            />
            <span className="text-ink-600">→</span>
            <select
              value={ruleForm.action}
              onChange={(e) => setRuleForm((f) => ({ ...f, action: e.target.value }))}
              className="rounded-lg border border-white/[0.08] bg-ink-950 px-2 py-1 text-[11px] text-ink-200 outline-none"
              aria-label="Rule action"
            >
              <option value="add_tag">add tag</option>
              <option value="star">star</option>
              <option value="archive">archive</option>
              <option value="set_color">set colour</option>
              <option value="add_to_collection">add to collection</option>
            </select>
            {(ruleForm.action === "add_tag" || ruleForm.action === "set_color" || ruleForm.action === "add_to_collection") && (
              <input
                value={ruleForm.actionValue}
                onChange={(e) => setRuleForm((f) => ({ ...f, actionValue: e.target.value }))}
                placeholder={ruleForm.action === "add_to_collection" ? "collection id" : ruleForm.action === "set_color" ? "ember" : "recipes"}
                className="h-7 w-28 rounded-lg border border-white/[0.08] bg-ink-950 px-2 text-[11px] text-ink-200 placeholder-ink-500 outline-none"
                aria-label="Rule action value"
              />
            )}
            <button
              onClick={() => void addRule()}
              disabled={!ruleForm.value.trim()}
              className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-200 disabled:opacity-40"
            >
              Add rule
            </button>
          </div>
        </div>
      )}

      {/* #421 Cleanup suggestions panel */}
      {showCleanup && (
        <div className="relative z-30 shrink-0 border-b border-ink-800 bg-ink-950/95 px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="micro-label">Cleanup assistant — nothing changes until you apply it</p>
            <button
              onClick={loadCleanup}
              className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:text-ink-100"
            >
              Refresh
            </button>
          </div>
          {!cleanupSuggestions ? (
            <div className="shimmer h-10 rounded-xl" />
          ) : cleanupSuggestions.length === 0 ? (
            <p className="py-2 text-xs text-ink-500">Nothing to clean up right now. Tidy vault.</p>
          ) : (
            <div className="max-h-56 space-y-1 overflow-y-auto">
              {cleanupSuggestions.map((s, i) => (
                <div key={`${s.kind}-${s.note_id}-${i}`} className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-1.5 text-[11.5px]">
                  <span
                    className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[9px] font-semibold uppercase ${
                      s.kind === "archive"
                        ? "bg-amber-500/15 text-amber-300"
                        : s.kind === "merge"
                          ? "bg-red-500/15 text-red-300"
                          : "bg-iris-500/15 text-iris-300"
                    }`}
                  >
                    {s.kind}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-ink-200">{s.title || s.note_id}</span>
                  <span className="hidden shrink-0 text-[10.5px] text-ink-500 lg:inline">{s.reason}</span>
                  {(s.kind === "archive" || s.kind === "add_tag") && (
                    <button
                      onClick={() => void applySuggestion(s)}
                      className="shrink-0 rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-[10.5px] font-medium text-emerald-200 hover:bg-emerald-500/20"
                    >
                      Apply
                    </button>
                  )}
                  <button
                    onClick={() => onOpen(s.note_id)}
                    className="shrink-0 rounded-lg border border-white/[0.08] bg-ink-900 px-2 py-0.5 text-[10.5px] text-ink-200 hover:text-ink-100"
                  >
                    {s.kind === "merge" || s.kind === "rename" ? "Open" : "View"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* #270 Tag tree panel */}
      {showTagTree && (
        <div className="relative z-30 shrink-0 border-b border-ink-800 bg-ink-950/95 px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="micro-label">Tags — click to filter, Alt-click to exclude</p>
          </div>
          {!tagCounts ? (
            <div className="shimmer h-10 rounded-xl" />
          ) : tagCounts.length === 0 ? (
            <p className="py-2 text-xs text-ink-500">No tags yet — tags come from captures and edits.</p>
          ) : (
            <div className="max-h-56 overflow-y-auto">
              {flattenTagTree(buildTagTree(tagCounts)).map(({ node, depth }) => {
                const active = tagMatches(node.full, tagFilter ?? "") && tagFilter === node.full;
                const excluded = excludedTag === node.full;
                return (
                  <button
                    key={node.full}
                    onClick={() => setTagFilter((cur) => (cur === node.full ? null : node.full))}
                    onClickCapture={(e) => {
                      if (e.altKey) {
                        e.stopPropagation();
                        setExcludedTag((cur) => (cur === node.full ? null : node.full));
                        setTagFilter(null);
                      }
                    }}
                    className={`flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-xs transition-colors ${
                      excluded
                        ? "text-red-300 line-through hover:bg-red-500/10"
                        : active
                          ? "bg-ember-500/15 font-medium text-ember-200"
                          : "text-ink-300 hover:bg-white/[0.04] hover:text-ink-100"
                    }`}
                    style={{ paddingLeft: `${8 + depth * 18}px` }}
                  >
                    <span className="truncate font-mono">{node.name}</span>
                    {node.children.length > 0 && (
                      <span className="font-mono text-[9px] text-ink-600">{node.children.length}▾</span>
                    )}
                    <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-500">
                      {node.total}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Collections dropdown */}
      {showCollections && (
        <div className="relative z-30 shrink-0 border-b border-ink-800 bg-ink-950/95 px-4 py-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="micro-label">Collections</p>
            <button
              onClick={() => void saveCurrentFilters()}
              className="rounded-lg border border-iris-400/30 bg-iris-500/10 px-2.5 py-1 text-[11px] font-medium text-iris-200 hover:bg-iris-500/20"
              title="Create a saved query from the active filters"
            >
              Save current filters
            </button>
          </div>
          {!collections ? (
            <div className="shimmer h-10 rounded-xl" />
          ) : collections.length === 0 ? (
            <p className="py-2 text-xs text-ink-500">
              No collections yet — save the current filters, or add one from a note in the drawer.
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
              {collections.map((c) => (
                <div
                  key={c.id}
                  className={`flex items-center gap-2 rounded-xl border px-3 py-2 transition-colors ${
                    activeCollection?.id === c.id
                      ? "border-iris-400/40 bg-iris-500/10"
                      : "border-white/[0.06] bg-white/[0.02] hover:border-iris-400/30"
                  }`}
                >
                  <button onClick={() => void openCollection(c.id)} className="min-w-0 flex-1 text-left">
                    <p className="truncate text-xs font-medium text-ink-100">{c.name}</p>
                    <p className="font-mono text-[9.5px] text-ink-500">
                      {c.kind}
                      {c.status ? ` · ${c.status}` : ""} · {c.item_count ?? 0}
                    </p>
                  </button>
                  <button
                    onClick={() => void deleteCollection(c.id)}
                    className="shrink-0 text-ink-500 transition-colors hover:text-red-300"
                    title="Delete collection (notes are kept)"
                    aria-label={`Delete collection ${c.name}`}
                  >
                    <XIcon className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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

        {/* #271 Triage mode */}
        {triageOpen ? (
          !triageCurrent ? (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="glass-studio flex h-14 w-14 items-center justify-center rounded-2xl">
                <CheckIcon className="h-6 w-6 text-emerald-400" />
              </div>
              <h2 className="mt-4 text-base font-semibold text-ink-100">Triage complete</h2>
              <p className="mt-1 text-xs text-ink-400">
                {triageDone.size > 0
                  ? `${triageDone.size} note${triageDone.size === 1 ? "" : "s"} filed this session.`
                  : "Nothing waiting to be filed."}
              </p>
              <button
                onClick={() => {
                  setTriageOpen(false);
                  setTriageDone(new Set());
                }}
                className="mt-4 rounded-lg border border-white/10 bg-ink-900 px-3.5 py-1.5 text-xs font-medium text-ink-200 hover:border-ember-400/40"
              >
                Back to inbox
              </button>
            </div>
          ) : (
            <div className="space-y-4 pt-2">
              <div className="flex items-center gap-2 px-1">
                <p className="micro-label !text-cyan-300">Triage</p>
                <span className="rounded-full bg-white/[0.05] px-2 py-0.2 font-mono text-[10px] text-ink-400">
                  {triageDone.size + 1} / {triageQueue.length + triageDone.size}
                </span>
                <div className="h-px flex-1 bg-gradient-to-r from-ink-500/20 via-ink-500/5 to-transparent" />
                <button
                  onClick={() => {
                    setTriageOpen(false);
                    setTriageDone(new Set());
                  }}
                  className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:text-ink-100"
                >
                  Exit triage
                </button>
              </div>
              <article
                {...activationProps(
                  `Open note: ${triageCurrent.title || triageCurrent.id}`,
                  () => onOpen(triageCurrent.id),
                )}
                className="glass rounded-2xl p-5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-ink-300">
                    {triageCurrent.type}
                  </span>
                  {triageCurrent.review_state === "raw" && (
                    <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10.5px] font-medium text-amber-300">
                      needs review
                    </span>
                  )}
                  <span className="ml-auto font-mono text-[10.5px] text-ink-500">
                    {relTime(triageCurrent.created_at)}
                  </span>
                </div>
                <h2 className="mt-2.5 text-lg font-semibold tracking-tight text-ink-100">
                  {triageCurrent.title || triageCurrent.raw_text.slice(0, 80) || "Untitled capture"}
                </h2>
                {triageCurrent.summary && (
                  <p className="mt-1.5 text-xs leading-relaxed text-ink-300">{triageCurrent.summary}</p>
                )}
                {triageCurrent.raw_text && (
                  <p className="mt-2 line-clamp-6 whitespace-pre-wrap text-xs leading-relaxed text-ink-400">
                    {triageCurrent.raw_text}
                  </p>
                )}
                {triageCurrent.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {triageCurrent.tags.map((t) => (
                      <span key={t} className="rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-[10.5px] text-ink-300">
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-white/[0.05] pt-3">
                  <button
                    onClick={() => void triageKeep(triageCurrent)}
                    className="rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25"
                    title="Keep it and mark reviewed"
                  >
                    Keep
                  </button>
                  <button
                    onClick={() => void triageArchive(triageCurrent)}
                    className="rounded-lg border border-white/[0.08] bg-ink-900 px-3 py-1.5 text-xs font-medium text-ink-200 hover:text-ink-100"
                  >
                    Archive
                  </button>
                  <button
                    onClick={() => void triageTrash(triageCurrent)}
                    className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-200 hover:bg-red-500/20"
                  >
                    Trash
                  </button>
                  <button
                    onClick={() => onOpen(triageCurrent.id)}
                    className="ml-auto rounded-lg px-2.5 py-1.5 text-xs text-ink-400 hover:text-ink-200"
                    title="Open the drawer to edit, tag or link before deciding"
                  >
                    Open in drawer →
                  </button>
                </div>
              </article>
            </div>
          )
        ) : activeCollection ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 px-1 pt-4">
              <FolderIcon className="h-3.5 w-3.5 text-iris-300" />
              <h2 className="micro-label !text-iris-200">{activeCollection.name}</h2>
              <span className="rounded-full bg-white/[0.05] px-2 py-0.2 font-mono text-[10px] text-ink-400">
                {activeCollection.kind} · {activeCollection.notes.length}
              </span>
              {activeCollection.description && (
                <span className="hidden truncate text-[11px] text-ink-500 md:inline">
                  {activeCollection.description}
                </span>
              )}
              <div className="h-px flex-1 bg-gradient-to-r from-ink-500/20 via-ink-500/5 to-transparent" />
              <button
                onClick={() => setActiveCollection(null)}
                className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:text-ink-100"
              >
                Exit collection
              </button>
            </div>
            {activeCollection.notes.length === 0 ? (
              <div className="glass rounded-2xl py-10 text-center">
                <p className="text-xs text-ink-400">
                  {activeCollection.kind === "saved_query"
                    ? "Nothing matches this saved query yet."
                    : "No notes in this collection yet — add them from a note's drawer."}
                </p>
              </div>
            ) : (
              <div className={gridCls}>
                {activeCollection.notes.map((n) => (
                  <NoteCard
                    key={n.id}
                    note={n}
                    highlight={selectedId === n.id}
                    onOpen={onOpen}
                    onPin={onPin}
                    onStar={onStar}
                    onUpdate={onNoteUpdated}
                    onToggleTask={handleToggleTask}
                    onRetry={handleRetry}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            )}
          </div>
        ) : showTrash ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 px-1 pt-4">
              <TrashIcon className="h-3.5 w-3.5 text-red-300" />
              <h2 className="micro-label !text-ink-300">Trash</h2>
              <span className="rounded-full bg-white/[0.05] px-2 py-0.2 font-mono text-[10px] text-ink-400">
                {trashLoading ? "…" : (trashNotes?.length ?? 0)}
              </span>
              <div className="h-px flex-1 bg-gradient-to-r from-ink-500/20 via-ink-500/5 to-transparent" />
              {trashNotes && trashNotes.length > 0 && (
                <button
                  onClick={() => void handleEmptyTrash()}
                  className="rounded-lg border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-[11px] font-medium text-red-200 hover:bg-red-500/20"
                >
                  Empty trash
                </button>
              )}
            </div>
            {trashLoading ? (
              <div className="shimmer h-16 rounded-2xl" />
            ) : !trashNotes || trashNotes.length === 0 ? (
              <div className="glass rounded-2xl py-10 text-center">
                <p className="text-xs text-ink-400">Trash is empty. Deleted notes rest here until auto-purge.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {trashNotes.map((n) => (
                  <div
                    key={n.id}
                    className="glass flex items-center gap-3 rounded-xl px-3.5 py-2.5"
                  >
                    <span className="micro-label w-14 shrink-0 !text-[9px]">{n.type}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-ink-200">
                      {n.title || n.raw_text.slice(0, 60) || "Untitled capture"}
                    </span>
                    <span className="hidden shrink-0 font-mono text-[10px] text-ink-500 sm:inline">
                      {n.trashed_at ? new Date(n.trashed_at).toLocaleDateString() : ""}
                    </span>
                    <button
                      onClick={() => void handleRestore(n.id)}
                      className="shrink-0 rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:border-emerald-400/40 hover:text-emerald-200"
                      title="Restore this note to the inbox"
                    >
                      Restore
                    </button>
                    <button
                      onClick={() => void handlePurge(n.id)}
                      className="shrink-0 rounded-lg border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-[11px] text-red-200 hover:bg-red-500/20"
                      title="Delete permanently — this cannot be undone"
                    >
                      Delete forever
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : notes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="glass-studio flex h-14 w-14 items-center justify-center rounded-2xl">
              <SparkIcon className="h-6 w-6 text-ember-400" />
            </div>
            <h2 className="mt-4 text-base font-semibold text-ink-100">Inbox is empty</h2>
            <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-400">
              Use the top command bar (<kbd className="font-mono text-ember-300">n</kbd>) to capture
              a note, voice memo, or YouTube video.
            </p>
            <div className="mt-4 flex items-center gap-2">
              <button
                onClick={onQuickStart}
                className="rounded-lg border border-white/10 bg-ink-900 px-3.5 py-1.5 text-xs font-medium text-ink-200 hover:border-ember-400/40"
              >
                Focus capture bar
              </button>
              {/* #488: deletable sample notes so a first run has something to poke */}
              <button
                onClick={async () => {
                  try {
                    const r = await api.createSamples();
                    if (r.ok) {
                      refreshNotes?.();
                      toast(`Created ${r.created} sample notes — trash them whenever`);
                    } else {
                      toast("Vault already has notes");
                    }
                  } catch (e) {
                    toast(e instanceof Error ? e.message : String(e), "err");
                  }
                }}
                className="rounded-lg border border-ember-400/30 bg-ember-500/10 px-3.5 py-1.5 text-xs font-medium text-ember-200 hover:bg-ember-500/20"
              >
                Create sample notes
              </button>
            </div>
          </div>
        ) : filteredNotes.length === 0 ? (
          <div className="glass rounded-2xl py-12 text-center">
            <p className="text-xs text-ink-400">No captures match the active filters.</p>
            <button
              onClick={() => {
                setTypeFilter("all");
                setTagFilter(null);
                setExcludedTag(null);
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
                      onStar={onStar}
                      onTagClick={(t) => setTagFilter((cur) => (cur === t ? null : t))}
                      onTagExclude={setExcludedTag}
                      onUpdate={onNoteUpdated}
                      onToggleTask={handleToggleTask}
                      onRetry={handleRetry}
                      onDelete={handleDelete}
                      selectMode={selectMode}
                      selected={picked.has(n.id)}
                      onToggleSelect={togglePick}
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
                      onStar={onStar}
                      onTagClick={(t) => setTagFilter((cur) => (cur === t ? null : t))}
                      onTagExclude={setExcludedTag}
                      onUpdate={onNoteUpdated}
                      onToggleTask={handleToggleTask}
                      onRetry={handleRetry}
                      onDelete={handleDelete}
                      selectMode={selectMode}
                      selected={picked.has(n.id)}
                      onToggleSelect={togglePick}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>

      {/* Bulk action bar */}
      {selectMode && (
        <div className="flex shrink-0 items-center gap-2 border-t border-ink-800 bg-ink-950 px-4 py-2.5">
          <span className="text-xs text-ink-300">
            <strong className="font-semibold text-ink-100">{picked.size}</strong> selected
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => void bulkAction("pin")}
              disabled={picked.size === 0}
              className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-xs text-ink-200 disabled:opacity-40"
            >
              Pin
            </button>
            <button
              onClick={() => void bulkAction("archive")}
              disabled={picked.size === 0}
              className="rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-xs text-ink-200 disabled:opacity-40"
            >
              Archive
            </button>
            <button
              onClick={() => void bulkAction("delete")}
              disabled={picked.size === 0}
              className="rounded-lg border border-red-500/40 bg-red-500/10 px-2.5 py-1 text-xs text-red-200 disabled:opacity-40"
            >
              Delete
            </button>
            <button
              onClick={() => {
                setSelectMode(false);
                setPicked(new Set());
              }}
              className="rounded-lg px-2.5 py-1 text-xs text-ink-400 hover:text-ink-200"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
