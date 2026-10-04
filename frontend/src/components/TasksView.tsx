import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { relTime } from "../time";
import {
  CalendarIcon,
  CheckIcon,
  EditIcon,
  FolderIcon,
  GitCommitIcon,
  ListIcon,
  SearchIcon,
  SendIcon,
  SparkIcon,
  TaskIcon,
  XIcon,
} from "./Icons";
import { Ring, StackBar } from "./charts";
import type { RepoInfo, TaskItem, TaskPriority } from "../types";

export interface TasksViewProps {
  refreshKey?: number;
  onOpenNote: (id: string) => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  onTasksChanged: () => void;
  initialTasks?: TaskItem[];
  initialRepos?: RepoInfo[];
  initialStatusFilter?: "open" | "done" | "all";
  initialPriorityFilter?: "all" | "P1" | "P2" | "P3";
  initialDueDateFilter?: "all" | "overdue" | "today" | "week";
  initialRepoFilter?: string;
  initialGroupMode?: "flat" | "priority" | "note";
  initialQuery?: string;
}

export function cyclePriority(current: TaskPriority): TaskPriority {
  if (current === "P1") return "P2";
  if (current === "P2") return "P3";
  return "P1";
}

export function toLocalDateString(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function formatDueDate(
  due_date: string | null,
  now: Date = new Date(),
  isDone = false
): { label: string; className: string } {
  if (!due_date) {
    return { label: "No date", className: "" };
  }

  const parts = due_date.split("-").map(Number);
  if (parts.length < 3 || isNaN(parts[0]) || isNaN(parts[1]) || isNaN(parts[2])) {
    return { label: due_date, className: "" };
  }
  const [y, m, d] = parts;

  const todayZero = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetZero = new Date(y, m - 1, d);

  const diffMs = targetZero.getTime() - todayZero.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays < 0) {
    const daysAgo = Math.abs(diffDays);
    const label = daysAgo === 1 ? "Overdue (yesterday)" : `Overdue by ${daysAgo}d`;
    if (isDone) {
      return {
        label,
        className: "text-ink-400 border border-ink-800/80 bg-ink-950/70",
      };
    }
    return {
      label,
      className: "due-overdue",
    };
  } else if (diffDays === 0) {
    return {
      label: "Today",
      className: isDone ? "text-ink-400 border border-ink-800/80 bg-ink-950/70" : "due-today",
    };
  } else if (diffDays === 1) {
    return {
      label: "Tomorrow",
      className: isDone ? "text-ink-400 border border-ink-800/80 bg-ink-950/70" : "due-soon",
    };
  } else if (diffDays <= 7) {
    return {
      label: `In ${diffDays}d`,
      className: isDone ? "text-ink-400 border border-ink-800/80 bg-ink-950/70" : "due-soon",
    };
  } else {
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const monthStr = monthNames[m - 1] ?? "";
    return {
      label: `${monthStr} ${d}`,
      className: "text-ink-400 border border-ink-800 bg-ink-950/70",
    };
  }
}

export function sortTasksStream(tasks: TaskItem[]): TaskItem[] {
  const prioOrder: Record<TaskPriority, number> = { P1: 1, P2: 2, P3: 3 };
  return [...tasks].sort((a, b) => {
    if (a.done !== b.done) return a.done ? 1 : -1;
    const prioDiff = (prioOrder[a.priority] || 2) - (prioOrder[b.priority] || 2);
    if (prioDiff !== 0) return prioDiff;
    if (a.due_date && b.due_date) {
      const dateDiff = a.due_date.localeCompare(b.due_date);
      if (dateDiff !== 0) return dateDiff;
    } else if (a.due_date && !b.due_date) {
      return -1;
    } else if (!a.due_date && b.due_date) {
      return 1;
    }
    return (b.created_at || "").localeCompare(a.created_at || "");
  });
}

export function groupTasksByPriority(tasks: TaskItem[]): Record<TaskPriority, TaskItem[]> {
  const grouped: Record<TaskPriority, TaskItem[]> = {
    P1: [],
    P2: [],
    P3: [],
  };
  for (const t of tasks) {
    if (t.priority === "P1") grouped.P1.push(t);
    else if (t.priority === "P3") grouped.P3.push(t);
    else grouped.P2.push(t);
  }
  return grouped;
}

export function groupTasksByNote(tasks: TaskItem[]): {
  noteId: string;
  title: string;
  createdAt: string;
  items: TaskItem[];
}[] {
  const map = new Map<
    string,
    { noteId: string; title: string; createdAt: string; items: TaskItem[] }
  >();
  for (const t of tasks) {
    const existing = map.get(t.note_id);
    if (existing) {
      existing.items.push(t);
    } else {
      map.set(t.note_id, {
        noteId: t.note_id,
        title: t.note_title || "Untitled capture",
        createdAt: t.created_at,
        items: [t],
      });
    }
  }
  return Array.from(map.values());
}

export async function toggleTaskAction(
  task: TaskItem,
  setTasks: (updater: (prev: TaskItem[]) => TaskItem[]) => void,
  onTasksChanged: () => void,
  onToast: (msg: string, kind?: "ok" | "err") => void
) {
  const nextDone = !task.done;
  setTasks((prev) =>
    (prev ?? []).map((t) => (t.id === task.id ? { ...t, done: nextDone } : t))
  );
  try {
    const updated = await api.toggleTask(task.id);
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, ...updated } : t))
    );
    onTasksChanged();
  } catch (e) {
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, done: task.done } : t))
    );
    onToast(e instanceof Error ? e.message : String(e), "err");
  }
}

export async function updateTaskPriorityAction(
  task: TaskItem,
  priority: TaskPriority,
  setTasks: (updater: (prev: TaskItem[]) => TaskItem[]) => void,
  onTasksChanged: () => void,
  onToast: (msg: string, kind?: "ok" | "err") => void
) {
  const oldPriority = task.priority;
  setTasks((prev) =>
    (prev ?? []).map((t) => (t.id === task.id ? { ...t, priority } : t))
  );
  try {
    const updated = await api.updateTask(task.id, { priority });
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, ...updated } : t))
    );
    onTasksChanged();
  } catch (e) {
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, priority: oldPriority } : t))
    );
    onToast(e instanceof Error ? e.message : String(e), "err");
  }
}

export async function updateTaskDueDateAction(
  task: TaskItem,
  dueDate: string | null,
  setTasks: (updater: (prev: TaskItem[]) => TaskItem[]) => void,
  onTasksChanged: () => void,
  onToast: (msg: string, kind?: "ok" | "err") => void
) {
  const oldDate = task.due_date;
  setTasks((prev) =>
    (prev ?? []).map((t) => (t.id === task.id ? { ...t, due_date: dueDate } : t))
  );
  try {
    const updated = await api.updateTask(task.id, { due_date: dueDate });
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, ...updated } : t))
    );
    onTasksChanged();
  } catch (e) {
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, due_date: oldDate } : t))
    );
    onToast(e instanceof Error ? e.message : String(e), "err");
  }
}

export async function updateTaskTextAction(
  task: TaskItem,
  text: string,
  setTasks: (updater: (prev: TaskItem[]) => TaskItem[]) => void,
  onTasksChanged: () => void,
  onToast: (msg: string, kind?: "ok" | "err") => void
) {
  const trimmed = text.trim();
  if (!trimmed || trimmed === task.text) return;
  const oldText = task.text;
  setTasks((prev) =>
    (prev ?? []).map((t) => (t.id === task.id ? { ...t, text: trimmed } : t))
  );
  try {
    const updated = await api.updateTask(task.id, { text: trimmed });
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, ...updated } : t))
    );
    onTasksChanged();
  } catch (e) {
    setTasks((prev) =>
      (prev ?? []).map((t) => (t.id === task.id ? { ...t, text: oldText } : t))
    );
    onToast(e instanceof Error ? e.message : String(e), "err");
  }
}

export async function createQuickTaskAction(
  data: {
    text: string;
    priority?: TaskPriority;
    due_date?: string | null;
    repo?: string | null;
    note_id?: string;
  },
  setTasks: (updater: (prev: TaskItem[]) => TaskItem[]) => void,
  onTasksChanged: () => void,
  onToast: (msg: string, kind?: "ok" | "err") => void
) {
  const trimmed = data.text.trim();
  if (!trimmed) return;
  try {
    const created = await api.createTask({
      ...data,
      text: trimmed,
    });
    setTasks((prev) => [created, ...(prev ?? [])]);
    onTasksChanged();
    onToast("task created");
  } catch (e) {
    onToast(e instanceof Error ? e.message : String(e), "err");
  }
}

export default function TasksView({
  refreshKey = 0,
  onOpenNote,
  onToast,
  onTasksChanged,
  initialTasks,
  initialRepos,
  initialStatusFilter = "open",
  initialPriorityFilter = "all",
  initialDueDateFilter = "all",
  initialRepoFilter = "all",
  initialGroupMode = "flat",
  initialQuery = "",
}: TasksViewProps) {
  const [tasks, setTasks] = useState<TaskItem[] | null>(initialTasks ?? null);
  const [repos, setRepos] = useState<RepoInfo[]>(initialRepos ?? []);

  const updateTasks = (updater: (prev: TaskItem[]) => TaskItem[]) => {
    setTasks((prev) => updater(prev ?? []));
  };

  // Multi-facet filters
  const [statusFilter, setStatusFilter] = useState<"open" | "done" | "all">(initialStatusFilter);
  const [priorityFilter, setPriorityFilter] = useState<"all" | "P1" | "P2" | "P3">(initialPriorityFilter);
  const [dueFilter, setDueFilter] = useState<"all" | "overdue" | "today" | "week">(initialDueDateFilter);
  const [repoFilter, setRepoFilter] = useState<string>(initialRepoFilter);
  const [query, setQuery] = useState(initialQuery);

  // Grouping mode: stream ("flat"), "priority", "note"
  const [groupMode, setGroupMode] = useState<"flat" | "priority" | "note">(initialGroupMode);

  // Quick task creator state
  const [newTaskText, setNewTaskText] = useState("");
  const [newTaskPriority, setNewTaskPriority] = useState<TaskPriority>("P2");
  const [newTaskRepo, setNewTaskRepo] = useState<string>("");
  const [newTaskDueDate, setNewTaskDueDate] = useState<string>("");
  const [creating, setCreating] = useState(false);

  // Inline editing state
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  // Due date picker popover active task id
  const [activeDatePickerTaskId, setActiveDatePickerTaskId] = useState<string | null>(null);

  // Load data
  useEffect(() => {
    let active = true;
    api
      .tasks({ status: "all" })
      .then((res) => {
        if (active) setTasks(res);
      })
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"));

    api
      .taskRepos()
      .then((res) => {
        if (active) setRepos(res);
      })
      .catch(() => {});

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function handleCreateTask() {
    const trimmed = newTaskText.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      await createQuickTaskAction(
        {
          text: trimmed,
          priority: newTaskPriority,
          repo: newTaskRepo || null,
          due_date: newTaskDueDate || null,
        },
        updateTasks,
        onTasksChanged,
        onToast
      );
      setNewTaskText("");
      setNewTaskDueDate("");
    } finally {
      setCreating(false);
    }
  }

  // Filtered tasks
  const filtered = useMemo(() => {
    if (!tasks) return [];
    const q = query.trim().toLowerCase();
    const todayStr = toLocalDateString();
    const weekEnd = toLocalDateString(new Date(Date.now() + 7 * 86400000));

    return tasks.filter((t) => {
      // Status
      if (statusFilter === "open" && t.done) return false;
      if (statusFilter === "done" && !t.done) return false;

      // Priority
      if (priorityFilter !== "all" && t.priority !== priorityFilter) return false;

      // Due date
      if (dueFilter === "overdue") {
        if (!t.due_date || t.due_date >= todayStr || t.done) return false;
      } else if (dueFilter === "today") {
        if (t.due_date !== todayStr) return false;
      } else if (dueFilter === "week") {
        if (!t.due_date || t.due_date < todayStr || t.due_date > weekEnd) return false;
      }

      // Repo
      if (repoFilter !== "all") {
        if ((t.repo || "").toLowerCase() !== repoFilter.toLowerCase()) return false;
      }

      // Query
      if (q) {
        const matchText = t.text.toLowerCase().includes(q);
        const matchNote = (t.note_title || "").toLowerCase().includes(q);
        const matchRepo = (t.repo || "").toLowerCase().includes(q);
        if (!matchText && !matchNote && !matchRepo) return false;
      }

      return true;
    });
  }, [tasks, statusFilter, priorityFilter, dueFilter, repoFilter, query]);

  // Completed fallback when zero open tasks match but completed tasks exist
  const completedFallback = useMemo(() => {
    if (!tasks) return [];
    return tasks.filter((t) => Boolean(t.done));
  }, [tasks]);

  const showingCompletedFallback =
    statusFilter === "open" &&
    filtered.length === 0 &&
    !query.trim() &&
    priorityFilter === "all" &&
    dueFilter === "all" &&
    repoFilter === "all" &&
    completedFallback.length > 0;

  const displayList = showingCompletedFallback ? completedFallback : filtered;

  // Stream sorting
  const streamSorted = useMemo(() => {
    return sortTasksStream(displayList);
  }, [displayList]);

  // By Priority grouping
  const priorityGrouped = useMemo(() => {
    return groupTasksByPriority(displayList);
  }, [displayList]);

  // By Note grouping
  const noteGrouped = useMemo(() => {
    return groupTasksByNote(displayList);
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
      {/* Multi-facet Toolbar */}
      <div className="app-toolbar flex flex-wrap items-center gap-2.5 px-5 py-2.5">
        {/* Status Tabs */}
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

        {/* Priority Filter Chips */}
        <div className="flex rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {(["all", "P1", "P2", "P3"] as const).map((p) => {
            const isSelected = priorityFilter === p;
            let badgeClass = "text-ink-400 hover:text-ink-200";
            if (isSelected) {
              if (p === "P1") badgeClass = "bg-red-500/20 text-red-400 font-semibold";
              else if (p === "P2") badgeClass = "bg-amber-500/20 text-amber-400 font-semibold";
              else if (p === "P3") badgeClass = "bg-slate-500/20 text-slate-300 font-semibold";
              else badgeClass = "bg-ink-800 text-ink-100 font-semibold";
            }
            return (
              <button
                key={p}
                onClick={() => setPriorityFilter(p)}
                className={`rounded-lg px-2.5 py-1 transition-all ${badgeClass}`}
              >
                {p === "all" ? "All" : p}
              </button>
            );
          })}
        </div>

        {/* Due Date Chips */}
        <div className="flex rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {[
            { id: "all" as const, label: "All Dates" },
            { id: "overdue" as const, label: "Overdue" },
            { id: "today" as const, label: "Today" },
            { id: "week" as const, label: "This Week" },
          ].map((d) => (
            <button
              key={d.id}
              onClick={() => setDueFilter(d.id)}
              className={`rounded-lg px-2.5 py-1 transition-all ${
                dueFilter === d.id
                  ? d.id === "overdue"
                    ? "bg-red-500/20 font-semibold text-red-400 shadow-xs"
                    : "bg-ink-800 font-semibold text-ink-100 shadow-xs"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>

        {/* Repo Dropdown Filter */}
        <div className="flex items-center rounded-xl border border-ink-800/90 bg-ink-950/85 px-2 py-0.5 text-xs">
          <GitCommitIcon className="mr-1.5 h-3.5 w-3.5 text-indigo-400" />
          <select
            value={repoFilter}
            onChange={(e) => setRepoFilter(e.target.value)}
            className="bg-transparent text-xs text-ink-200 outline-none cursor-pointer"
          >
            <option value="all">All Repos</option>
            {repos.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name} ({r.task_count ?? 0})
              </option>
            ))}
          </select>
        </div>

        {/* Grouping Modes */}
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
            onClick={() => setGroupMode("priority")}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition-all ${
              groupMode === "priority"
                ? "bg-ember-500/20 font-medium text-ember-300"
                : "text-ink-400 hover:text-ink-200"
            }`}
          >
            <TaskIcon className="h-3 w-3" /> By Priority
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

        {/* Search Input */}
        <div className="relative ml-auto w-56">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search action items…"
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

      {/* Main Content Area */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        {/* Top Deck: Telemetry Card + Enhanced Quick Task Creator */}
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-12">
          {/* Telemetry Card */}
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
                    Streamlined action workbench with priority routing &amp; Git repo awareness
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

          {/* Enhanced Quick Task Creator */}
          <div className="glass-studio flex flex-col justify-between rounded-2xl p-4 lg:col-span-5">
            <div className="flex items-center justify-between">
              <span className="micro-label flex items-center gap-1.5">
                <SparkIcon className="h-3 w-3 text-ember-400" />
                New Action Item
              </span>
              <div className="flex items-center gap-2">
                {/* Priority Selector */}
                <div className="flex rounded-lg border border-ink-800/80 bg-ink-950/80 p-0.5 text-[10px]">
                  {(["P1", "P2", "P3"] as const).map((p) => (
                    <button
                      key={p}
                      onClick={() => setNewTaskPriority(p)}
                      className={`rounded px-1.5 py-0.5 font-mono font-semibold transition-colors ${
                        newTaskPriority === p
                          ? p === "P1"
                            ? "bg-red-500/20 text-red-400"
                            : p === "P2"
                            ? "bg-amber-500/20 text-amber-400"
                            : "bg-slate-500/20 text-slate-300"
                          : "text-ink-500 hover:text-ink-300"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>

                {/* Repo Selector */}
                {repos.length > 0 && (
                  <select
                    value={newTaskRepo}
                    onChange={(e) => setNewTaskRepo(e.target.value)}
                    className="rounded-lg border border-ink-800/80 bg-ink-950/80 px-2 py-0.5 font-mono text-[10px] text-ink-300 outline-none"
                  >
                    <option value="">No repo</option>
                    {repos.map((r) => (
                      <option key={r.name} value={r.name}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            <div className="mt-2.5 flex items-center gap-2">
              <input
                value={newTaskText}
                onChange={(e) => setNewTaskText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) {
                    void handleCreateTask();
                  }
                }}
                placeholder="Add a new task or action item…"
                className="h-9 flex-1 rounded-xl border border-ink-800 bg-ink-950/90 px-3 text-xs text-ink-100 placeholder-ink-500 outline-none transition-colors focus:border-ember-500/50"
              />
              <button
                onClick={() => void handleCreateTask()}
                disabled={!newTaskText.trim() || creating}
                className="flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-gradient-to-br from-ember-400 to-ember-600 px-3.5 text-xs font-semibold text-ink-950 shadow-sm transition-all hover:brightness-110 disabled:opacity-40"
              >
                <SendIcon className="h-3 w-3" />
                <span>Add Task</span>
              </button>
            </div>
          </div>
        </div>

        {/* All Caught Up Banner */}
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

        {/* Tasks Display */}
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
          // Stream Mode
          <div className="space-y-2">
            {streamSorted.map((t) => renderTaskRow(t))}
          </div>
        ) : groupMode === "priority" ? (
          // By Priority Mode: Separate sections for P1, P2, P3
          <div className="space-y-4">
            {(
              [
                { p: "P1" as const, title: "P1 — Urgent", border: "border-red-500/30", color: "text-red-400", bg: "bg-red-500/10" },
                { p: "P2" as const, title: "P2 — Normal", border: "border-amber-500/30", color: "text-amber-400", bg: "bg-amber-500/10" },
                { p: "P3" as const, title: "P3 — Low", border: "border-slate-500/30", color: "text-slate-400", bg: "bg-slate-500/10" },
              ] as const
            ).map((section) => {
              const items = priorityGrouped[section.p] ?? [];
              if (items.length === 0) return null;
              return (
                <div key={section.p} className="glass-studio rounded-2xl p-4">
                  <div className="mb-3 flex items-center justify-between border-b border-ink-800/80 pb-2">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-md border px-2 py-0.5 text-xs font-bold ${section.border} ${section.bg} ${section.color}`}>
                        {section.title}
                      </span>
                    </div>
                    <span className="font-mono text-xs text-ink-400">
                      {items.length} {items.length === 1 ? "task" : "tasks"}
                    </span>
                  </div>
                  <div className="space-y-2">
                    {items.map((t) => renderTaskRow(t))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          // By Note Mode
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {noteGrouped.map((g) => {
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
                      {g.items.map((t) => renderTaskRow(t, true))}
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

  // Task Row Renderer
  function renderTaskRow(t: TaskItem, compact = false) {
    const isDone = Boolean(t.done);
    const isEditing = editingTaskId === t.id;
    const dueInfo = formatDueDate(t.due_date, undefined, isDone);
    const isDatePickerOpen = activeDatePickerTaskId === t.id;

    const prioBadgeClass =
      t.priority === "P1"
        ? "badge-p1"
        : t.priority === "P2"
        ? "badge-p2"
        : "badge-p3";

    return (
      <div
        key={t.id}
        className={`glass card-hover group relative flex items-center gap-3 rounded-2xl px-3.5 py-2.5 transition-all ${
          isDone ? "opacity-75" : ""
        }`}
      >
        {/* Checkbox */}
        <button
          onClick={() => void toggleTaskAction(t, updateTasks, onTasksChanged, onToast)}
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all ${
            isDone
              ? "border-emerald-500/80 bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
              : "border-ink-600 bg-ink-950/80 hover:border-ember-400"
          }`}
          title={isDone ? "Reopen task" : "Mark task complete"}
        >
          {isDone && <CheckIcon className="h-3.5 w-3.5" />}
        </button>

        {/* Priority Badge / Pill (Click to cycle P1 -> P2 -> P3) */}
        <button
          onClick={() => {
            const nextPrio = cyclePriority(t.priority);
            void updateTaskPriorityAction(t, nextPrio, updateTasks, onTasksChanged, onToast);
          }}
          className={`${prioBadgeClass} cursor-pointer transition-transform hover:scale-105`}
          title={`Priority ${t.priority} — click to cycle (P1 -> P2 -> P3)`}
        >
          {t.priority}
        </button>

        {/* Task Text / Inline Editor */}
        <div className="min-w-0 flex-1">
          {isEditing ? (
            <input
              autoFocus
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  void updateTaskTextAction(t, editText, updateTasks, onTasksChanged, onToast);
                  setEditingTaskId(null);
                } else if (e.key === "Escape") {
                  setEditingTaskId(null);
                }
              }}
              onBlur={() => {
                void updateTaskTextAction(t, editText, updateTasks, onTasksChanged, onToast);
                setEditingTaskId(null);
              }}
              className="w-full rounded border border-ember-500/50 bg-ink-950/90 px-2 py-0.5 text-xs text-ink-100 outline-none"
            />
          ) : (
            <div className="flex items-center gap-1.5">
              <span
                onClick={() => {
                  setEditingTaskId(t.id);
                  setEditText(t.text);
                }}
                className={`selectable cursor-text text-[13px] font-medium transition-colors hover:text-ember-300 ${
                  isDone ? "text-ink-400 line-through decoration-ink-600" : "text-ink-100"
                }`}
                title="Click to edit task title"
              >
                {t.text}
              </span>
              <button
                onClick={() => {
                  setEditingTaskId(t.id);
                  setEditText(t.text);
                }}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-ink-500 hover:text-ink-300"
                title="Edit title"
              >
                <EditIcon className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>

        {/* Right Controls: Repo, Due Date, Source Note */}
        <div className="flex shrink-0 items-center gap-2">
          {/* Repo Tag */}
          {t.repo && (
            <button
              onClick={() => setRepoFilter(t.repo || "all")}
              className="badge-repo cursor-pointer"
              title={`Filtered by repo: ${t.repo}`}
            >
              {t.repo}
            </button>
          )}

          {/* Due Date Pill / Quick Picker */}
          <div className="relative">
            <button
              onClick={() => setActiveDatePickerTaskId(isDatePickerOpen ? null : t.id)}
              className={`text-[11px] font-medium transition-transform hover:scale-105 ${
                dueInfo.className || "rounded-lg border border-ink-800 bg-ink-950/70 px-2 py-0.5 text-ink-400"
              }`}
              title="Click to change due date"
            >
              <CalendarIcon className="mr-1 inline h-3 w-3" />
              {dueInfo.label}
            </button>

            {/* Quick Date Popover */}
            {isDatePickerOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={(e) => {
                    e.stopPropagation();
                    setActiveDatePickerTaskId(null);
                  }}
                />
                <div className="absolute right-0 z-50 mt-1 flex w-44 flex-col gap-1 rounded-xl border border-ink-800 bg-ink-950 p-2 shadow-xl">
                  <span className="font-mono text-[10px] text-ink-400 px-1">Quick Due Date</span>
                  <button
                    onClick={() => {
                      const todayStr = toLocalDateString();
                      void updateTaskDueDateAction(t, todayStr, updateTasks, onTasksChanged, onToast);
                      setActiveDatePickerTaskId(null);
                    }}
                    className="rounded px-2 py-1 text-left text-xs text-ink-200 hover:bg-ink-800"
                  >
                    Today
                  </button>
                  <button
                    onClick={() => {
                      const tomStr = toLocalDateString(new Date(Date.now() + 86400000));
                      void updateTaskDueDateAction(t, tomStr, updateTasks, onTasksChanged, onToast);
                      setActiveDatePickerTaskId(null);
                    }}
                    className="rounded px-2 py-1 text-left text-xs text-ink-200 hover:bg-ink-800"
                  >
                    Tomorrow
                  </button>
                  <button
                    onClick={() => {
                      const weekStr = toLocalDateString(new Date(Date.now() + 7 * 86400000));
                      void updateTaskDueDateAction(t, weekStr, updateTasks, onTasksChanged, onToast);
                      setActiveDatePickerTaskId(null);
                    }}
                    className="rounded px-2 py-1 text-left text-xs text-ink-200 hover:bg-ink-800"
                  >
                    Next Week
                  </button>
                  <input
                    type="date"
                    value={t.due_date ?? ""}
                    onChange={(e) => {
                      void updateTaskDueDateAction(t, e.target.value || null, updateTasks, onTasksChanged, onToast);
                      setActiveDatePickerTaskId(null);
                    }}
                    className="rounded border border-ink-800 bg-ink-900 px-2 py-1 text-xs text-ink-200 outline-none"
                  />
                  {t.due_date && (
                    <button
                      onClick={() => {
                        void updateTaskDueDateAction(t, null, updateTasks, onTasksChanged, onToast);
                        setActiveDatePickerTaskId(null);
                      }}
                      className="rounded px-2 py-1 text-left text-xs text-red-400 hover:bg-ink-800"
                    >
                      Clear date
                    </button>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Source Note Button */}
          {!compact && (
            <button
              onClick={() => onOpenNote(t.note_id)}
              className="max-w-44 truncate rounded-lg border border-ink-800 bg-ink-950/75 px-2.5 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:border-ember-400/40 hover:text-ember-300"
              title="Open source note"
            >
              {t.note_title || "Untitled capture"}
            </button>
          )}

          {/* Timestamp */}
          {!compact && (
            <span className="w-14 text-right font-mono text-[10.5px] text-ink-400">
              {relTime(t.created_at)}
            </span>
          )}
        </div>
      </div>
    );
  }
}
