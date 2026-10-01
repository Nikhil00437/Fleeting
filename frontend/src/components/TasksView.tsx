import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { relTime } from "../time";
import {
  CheckIcon,
  FolderIcon,
  ListIcon,
  SearchIcon,
  SendIcon,
  SparkIcon,
  TaskIcon,
  XIcon,
} from "./Icons";
import { Ring, StackBar } from "./charts";
import type { Note, TaskRef } from "../types";

interface Props {
  refreshKey: number;
  onOpenNote: (id: string) => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  onTasksChanged: () => void;
  onNoteCreated?: (note: Note) => void;
}

export default function TasksView({
  refreshKey,
  onOpenNote,
  onToast,
  onTasksChanged,
  onNoteCreated,
}: Props) {
  const [tasks, setTasks] = useState<TaskRef[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<"open" | "done" | "all">("open");
  const [groupMode, setGroupMode] = useState<"flat" | "note">("flat");
  const [query, setQuery] = useState("");
  const [newTaskText, setNewTaskText] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    api
      .tasks(true)
      .then(setTasks)
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function createQuickTask() {
    const trimmed = newTaskText.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      const prefix = /^todo:/i.test(trimmed) ? trimmed : `todo: ${trimmed}`;
      const note = await api.captureText(prefix);
      setNewTaskText("");
      onNoteCreated?.(note);
      onToast("task captured — extracting action item");
      window.setTimeout(() => {
        onTasksChanged();
      }, 650);
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setCreating(false);
    }
  }

  async function toggleTask(task: TaskRef) {
    const key = task.note_id + task.item_id;
    const nextDone = !task.done;
    setPendingIds((s) => new Set(s).add(key));
    setTasks((list) =>
      (list ?? []).map((t) =>
        t.note_id === task.note_id && t.item_id === task.item_id ? { ...t, done: nextDone } : t,
      ),
    );
    try {
      const note = await api.note(task.note_id);
      const items = note.action_items.map((it) =>
        it.id === task.item_id ? { ...it, done: nextDone } : it,
      );
      await api.updateNote(note.id, { action_items: items } as never);
      onTasksChanged();
    } catch (e) {
      setTasks((list) =>
        (list ?? []).map((t) =>
          t.note_id === task.note_id && t.item_id === task.item_id ? { ...t, done: task.done } : t,
        ),
      );
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setPendingIds((s) => {
        const next = new Set(s);
        next.delete(key);
        return next;
      });
    }
  }

  const filtered = useMemo(() => {
    if (!tasks) return [];
    const q = query.trim().toLowerCase();
    return tasks.filter((t) => {
      const isDone = Boolean(t.done);
      if (statusFilter === "open" && isDone) return false;
      if (statusFilter === "done" && !isDone) return false;
      if (q) {
        return (
          t.text.toLowerCase().includes(q) ||
          (t.note_title || "").toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [tasks, statusFilter, query]);

  const completedFallback = useMemo(() => {
    if (!tasks) return [];
    return tasks.filter((t) => Boolean(t.done));
  }, [tasks]);

  const displayList =
    statusFilter === "open" && filtered.length === 0 && !query.trim() && completedFallback.length > 0
      ? completedFallback
      : filtered;

  const showingCompletedFallback =
    statusFilter === "open" && filtered.length === 0 && !query.trim() && completedFallback.length > 0;

  const groupedByNote = useMemo(() => {
    const map = new Map<
      string,
      { noteId: string; title: string; createdAt: string; items: TaskRef[] }
    >();
    for (const t of displayList) {
      const existing = map.get(t.note_id);
      if (existing) existing.items.push(t);
      else
        map.set(t.note_id, {
          noteId: t.note_id,
          title: t.note_title || "Untitled capture",
          createdAt: t.created_at,
          items: [t],
        });
    }
    return Array.from(map.values());
  }, [displayList]);

  if (tasks === null) {
    return (
      <div className="space-y-2.5 p-5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="shimmer h-14 rounded-2xl" />
        ))}
      </div>
    );
  }

  const doneCount = tasks.filter((t) => t.done).length;
  const openCount = tasks.filter((t) => !t.done).length;
  const total = doneCount + openCount;
  const completion = total > 0 ? doneCount / total : 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Docked Pane Toolbar */}
      <div className="app-toolbar flex h-12 shrink-0 items-center gap-2.5 px-5">
        <div className="flex rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {[
            { id: "open" as const, label: "Open", count: openCount },
            { id: "done" as const, label: "Completed", count: doneCount },
            { id: "all" as const, label: "All", count: total },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition-all ${
                statusFilter === tab.id
                  ? "bg-ink-800 font-semibold text-ink-100 shadow-xs"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              <span>{tab.label}</span>
              <span
                className={`rounded-md px-1.5 py-0.2 font-mono text-[10px] ${
                  statusFilter === tab.id
                    ? "bg-ink-950/70 text-ember-300"
                    : "text-ink-500"
                }`}
              >
                {tab.count}
              </span>
            </button>
          ))}
        </div>

        <div className="flex rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          <button
            onClick={() => setGroupMode("flat")}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition-all ${
              groupMode === "flat"
                ? "bg-ember-500/20 font-medium text-ember-300"
                : "text-ink-400 hover:text-ink-200"
            }`}
          >
            <ListIcon className="h-3 w-3" /> Stream
          </button>
          <button
            onClick={() => setGroupMode("note")}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition-all ${
              groupMode === "note"
                ? "bg-ember-500/20 font-medium text-ember-300"
                : "text-ink-400 hover:text-ink-200"
            }`}
          >
            <FolderIcon className="h-3 w-3" /> By Note
          </button>
        </div>

        <div className="relative ml-auto w-60">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter action items…"
            className="h-8 w-full rounded-xl border border-ink-800/90 bg-ink-950/85 pr-7 pl-8 text-xs text-ink-100 placeholder-ink-500 outline-none transition-colors focus:border-ember-500/50"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute top-1/2 right-2.5 -translate-y-1/2 text-ink-400 hover:text-ink-200"
            >
              <XIcon className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Scrollable Tasks Workbench */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {/* Top Deck: Telemetry Card + Inline Quick Task Creator */}
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-12">
          <div className="glass-studio flex items-center gap-4 rounded-2xl p-4 lg:col-span-7">
            <Ring
              progress={completion}
              color="#10b981"
              size={62}
              thickness={6}
              label={`${Math.round(completion * 100)}%`}
            />
            <div className="min-w-0 flex-1 space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h2 className="text-xs font-semibold text-ink-100">Action Item Velocity</h2>
                  <p className="text-[11px] text-ink-400">
                    Extracted automatically from notes, voice memos, and YouTube captures
                  </p>
                </div>
                <div className="flex items-center gap-2 font-mono text-xs">
                  <button
                    onClick={() => setStatusFilter("open")}
                    className={`rounded-lg border px-2 py-0.5 transition-colors ${
                      statusFilter === "open"
                        ? "border-ember-400/40 bg-ember-500/15 text-ember-300"
                        : "border-ink-800 bg-ink-950/60 text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    Open: <strong>{openCount}</strong>
                  </button>
                  <button
                    onClick={() => setStatusFilter("done")}
                    className={`rounded-lg border px-2 py-0.5 transition-colors ${
                      statusFilter === "done"
                        ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-300"
                        : "border-ink-800 bg-ink-950/60 text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    Done: <strong>{doneCount}</strong>
                  </button>
                </div>
              </div>
              <StackBar
                segments={[
                  {
                    key: "done",
                    value: doneCount,
                    color: "#4b786b",
                    title: `Completed: ${doneCount}`,
                  },
                  {
                    key: "open",
                    value: openCount,
                    color: "#bd5d38",
                    title: `Open: ${openCount}`,
                  },
                ]}
                selectedKey={statusFilter === "all" ? null : statusFilter}
                onSelect={(k) => setStatusFilter(k as "open" | "done")}
              />
            </div>
          </div>

          {/* Inline Task Creator */}
          <div className="glass-studio flex flex-col justify-between rounded-2xl p-4 lg:col-span-5">
            <div className="flex items-center justify-between">
              <span className="micro-label flex items-center gap-1.5">
                <SparkIcon className="h-3 w-3 text-ember-400" />
                New Action Item
              </span>
              <span className="font-mono text-[10px] text-ink-400">Syncs to Inbox & Vault</span>
            </div>
            <div className="mt-2.5 flex items-center gap-2">
              <input
                value={newTaskText}
                onChange={(e) => setNewTaskText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    void createQuickTask();
                  }
                }}
                placeholder="Add a new task or action item…"
                className="h-9 flex-1 rounded-xl border border-ink-800 bg-ink-950/90 px-3 text-xs text-ink-100 placeholder-ink-500 outline-none transition-colors focus:border-ember-500/50"
              />
              <button
                onClick={() => void createQuickTask()}
                disabled={!newTaskText.trim() || creating}
                className="flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-gradient-to-br from-ember-400 to-ember-600 px-3.5 text-xs font-semibold text-ink-950 shadow-sm transition-all hover:brightness-110 disabled:opacity-40"
              >
                <SendIcon className="h-3 w-3" />
                <span>Add Task</span>
              </button>
            </div>
          </div>
        </div>

        {/* All Caught Up Banner when Open == 0 but Done > 0 */}
        {showingCompletedFallback && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-emerald-500/25 bg-emerald-500/[0.07] px-4 py-3">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-400/30">
                <CheckIcon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-xs font-semibold text-ink-100">
                  Inbox Zero for Tasks — all {doneCount} action items completed
                </p>
                <p className="text-[11px] text-ink-300">
                  Showing your recently completed tasks below. Uncheck any item to reopen it.
                </p>
              </div>
            </div>
            <span className="rounded-lg border border-emerald-400/30 bg-emerald-500/15 px-2.5 py-1 font-mono text-[10.5px] font-semibold text-emerald-300">
              100% Complete
            </span>
          </div>
        )}

        {/* Task List or By-Note Grid */}
        {displayList.length === 0 ? (
          <div className="glass-studio flex flex-col items-center justify-center rounded-2xl py-16 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ember-500/15 text-ember-300 ring-1 ring-ember-400/30">
              <TaskIcon className="h-5 w-5" />
            </div>
            <h3 className="mt-3 text-sm font-semibold text-ink-100">No matching tasks</h3>
            <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-400">
              Add a task above or capture a note containing an action item.
            </p>
          </div>
        ) : groupMode === "flat" ? (
          <div className="space-y-2">
            {showingCompletedFallback && (
              <div className="flex items-center justify-between px-1 pt-1">
                <span className="micro-label">Recently Completed ({displayList.length})</span>
                <span className="font-mono text-[10.5px] text-ink-400">
                  Click source note to open inspector
                </span>
              </div>
            )}
            {displayList.map((t) => {
              const isDone = Boolean(t.done);
              const busy = pendingIds.has(t.note_id + t.item_id);
              return (
                <div
                  key={t.note_id + t.item_id}
                  className="glass card-hover group flex items-center gap-3.5 rounded-2xl px-4 py-3"
                >
                  <button
                    onClick={() => void toggleTask(t)}
                    disabled={busy}
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all ${
                      isDone
                        ? "border-emerald-500/80 bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                        : "border-ink-600 bg-ink-950/80 hover:border-ember-400"
                    }`}
                    title={isDone ? "Reopen task" : "Mark task complete"}
                  >
                    {isDone && <CheckIcon className="h-3.5 w-3.5" />}
                  </button>

                  <div className="min-w-0 flex-1">
                    <p
                      className={`selectable text-[13px] font-medium ${
                        isDone ? "text-ink-300 line-through decoration-ink-600" : "text-ink-100"
                      }`}
                    >
                      {t.text}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-2.5">
                    <button
                      onClick={() => onOpenNote(t.note_id)}
                      className="max-w-56 truncate rounded-lg border border-ink-800 bg-ink-950/75 px-2.5 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:border-ember-400/40 hover:text-ember-300"
                      title="Open source note"
                    >
                      {t.note_title || "Untitled capture"}
                    </button>
                    <span className="w-16 text-right font-mono text-[10.5px] text-ink-400">
                      {relTime(t.created_at)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {groupedByNote.map((g) => {
              const groupDone = g.items.filter((i) => i.done).length;
              return (
                <div key={g.noteId} className="glass-studio flex flex-col justify-between rounded-2xl p-4">
                  <div>
                    <div className="mb-3 flex items-center justify-between gap-2 border-b border-ink-800/80 pb-2.5">
                      <button
                        onClick={() => onOpenNote(g.noteId)}
                        className="truncate text-left text-xs font-semibold text-ink-100 transition-colors hover:text-ember-300"
                      >
                        {g.title}
                      </button>
                      <div className="flex shrink-0 items-center gap-2">
                        <span className="rounded-md border border-ink-800 bg-ink-950/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
                          {groupDone}/{g.items.length}
                        </span>
                        <span className="font-mono text-[10px] text-ink-400">
                          {relTime(g.createdAt)}
                        </span>
                      </div>
                    </div>
                    <div className="space-y-2">
                      {g.items.map((t) => {
                        const isDone = Boolean(t.done);
                        return (
                          <div
                            key={t.item_id}
                            className="flex items-start gap-2.5 rounded-xl border border-ink-800/50 bg-ink-950/50 px-3 py-2 text-xs"
                          >
                            <button
                              onClick={() => void toggleTask(t)}
                              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                                isDone
                                  ? "border-emerald-500/80 bg-emerald-500/20 text-emerald-300"
                                  : "border-ink-600 hover:border-ember-400"
                              }`}
                            >
                              {isDone && <CheckIcon className="h-3 w-3" />}
                            </button>
                            <span
                              className={`selectable leading-relaxed ${
                                isDone ? "text-ink-400 line-through" : "text-ink-100"
                              }`}
                            >
                              {t.text}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
