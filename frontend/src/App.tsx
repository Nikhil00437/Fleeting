import { createPortal, flushSync } from "react-dom";
import { vt } from "./motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { applyServerEvent, emptyServerState, type ServerState } from "./components/serverEvents";
import { api } from "./api";
import { fmtSecs, prettyAppName } from "./apps";
import CaptureBar from "./components/CaptureBar";
import { Spark } from "./components/charts";
import Inbox from "./components/Inbox";
import { FleetingMark } from "./components/Icons";
import NoteDrawer from "./components/NoteDrawer";
import SearchView from "./components/SearchView";
import SettingsView from "./components/SettingsView";
import TasksView from "./components/TasksView";
import TimelineView from "./components/TimelineView";
import ReportsView from "./components/ReportsView";
import CaptureHud from "./components/CaptureHud";
import AssistantView from "./components/AssistantView";
import ProcessesView from "./components/ProcessesView";
import DictationView from "./components/DictationView";
import {
 ActivityIcon,
 BotIcon,
 ClockIcon,
 CpuIcon,
 MicIcon,
 SearchIcon,
 FileIcon,
 SettingsIcon,
 SparkIcon,
 TaskIcon,
 TerminalIcon,
 TextIcon,
 XIcon,
} from "./components/Icons";
import type { Note, Stats, WhisperProgress } from "./types";

type View =
  | "inbox"
  | "timeline"
  | "reports"
  | "tasks"
  | "search"
  | "settings"
  | "assistant"
  | "processes"
  | "dictation";

interface ToastAction {
 label: string;
 run: () => void;
}

interface Toast {
 id: number;
 message: string;
 kind: "ok" | "err";
 actions?: ToastAction[];
}

export default function App() {
 const isHudMode =
  typeof window !== "undefined" &&
  (new URLSearchParams(window.location.search).get("mode") === "hud" ||
   window.location.hash === "#hud" ||
   new URLSearchParams(window.location.hash.slice(1)).get("mode") === "hud");

 if (isHudMode) {
  return <CaptureHud />;
 }

 const [view, setViewRaw] = useState<View>("inbox");
 const setView = (v: View) => vt(() => flushSync(() => setViewRaw(v)));
 const [notes, setNotes] = useState<Note[]>([]);
 const [stats, setStats] = useState<Stats | null>(null);
 const [selectedId, setSelectedRaw] = useState<string | null>(null);
 const setSelectedId = (id: React.SetStateAction<string | null>) => vt(() => flushSync(() => setSelectedRaw(id)));
 const [toasts, setToasts] = useState<Toast[]>([]);
 const [loading, setLoading] = useState(true);
 const [trackedToday, setTrackedToday] = useState(0);
 const [liveApp, setLiveApp] = useState<string | null>(null);
 // True while the SSE stream is disconnected, so the UI can say so.
 const [streamDown, setStreamDown] = useState(false);
 // Latest embedding-migration progress, from the SSE reducer.
 const [embedding, setEmbedding] = useState<Record<string, unknown> | null>(null);
 const [backfillBusy, setBackfillBusy] = useState(false);
 const [week, setWeek] = useState<number[]>([0, 0, 0, 0, 0, 0, 0]);
 const [whisperProgress, setWhisperProgress] = useState<WhisperProgress | null>(null);

 // Electron & Desktop Workbench State
 const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
 const [isMaximized, setIsMaximized] = useState(false);
 const [cmdOpen, setCmdOpen] = useState(false);
 const [cmdQuery, setCmdQuery] = useState("");
 const [cmdIndex, setCmdIndex] = useState(0);

 const captureRef = useRef<HTMLInputElement | null>(null);
 const searchRef = useRef<HTMLInputElement | null>(null);
 const cmdInputRef = useRef<HTMLInputElement | null>(null);
 const toastSeq = useRef(0);
 const [tasksKey, setTasksKey] = useState(0);
 const [timelineKey, setTimelineKey] = useState(0);
 const [collectionsKey, setCollectionsKey] = useState(0);

 const desktop = typeof window !== "undefined" ? window.fleetingDesktop : undefined;
 const isElectron = Boolean(desktop?.isElectron);

 const toast = useCallback((message: string, kind: "ok" | "err" = "ok", actions?: ToastAction[]) => {
  const id = ++toastSeq.current;
  // #84: stacking limit — oldest toast drops first
  setToasts((t) => [...t.slice(-3), { id, message, kind, actions }]);
  window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), actions ? 5000 : 4200);
 }, []);

 const refreshStats = useCallback(() => {
  api.stats().then(setStats).catch(() => {});
  api.activityDay().then((d) => setTrackedToday(d.total_seconds)).catch(() => {});
  api.activityWeek(7).then((d) => setWeek(d.map((x) => x.seconds))).catch(() => {});
 }, []);

 const mergeNote = useCallback((note: Note) => {
  setNotes((list) => {
   const idx = list.findIndex((n) => n.id === note.id);
   if (idx === -1) return [note, ...list];
   const next = [...list];
   next[idx] = note;
   return next;
  });
 }, []);

 const removeNote = useCallback(
  (id: string) => {
   setNotes((list) => list.filter((n) => n.id !== id));
   setSelectedId((cur) => (cur === id ? null : cur));
   refreshStats();
  },
  [refreshStats],
 );

 const refetchNotes = useCallback(() => {
  api
   .notes({ limit: "200" })
   .then(setNotes)
   .catch(() => {});
 }, []);

 useEffect(() => {
  api
   .notes({ limit: "200" })
   .then(setNotes)
   .catch((e) => toast(e instanceof Error ? e.message : String(e), "err"))
   .finally(() => setLoading(false));
  refreshStats();
 }, [toast, refreshStats]);

 // Electron IPC listeners (window state & tray navigation)
 useEffect(() => {
  if (!desktop) return;
  desktop.isMaximized().then(setIsMaximized).catch(() => {});
  const offMax = desktop.onMaximizeChange(setIsMaximized);
  const offNav = desktop.onNavigate((target) => {
   if (target === "capture") {
    captureRef.current?.focus();
   } else if (
    target === "inbox" ||
    target === "timeline" ||
    target === "reports" ||
    target === "tasks" ||
    target === "search" ||
    target === "settings" ||
    target === "assistant" ||
     target === "processes" ||
     target === "dictation"
   ) {
    setView(target);
   }
  });
  return () => {
   offMax();
   offNav();
  };
 }, [desktop]);

 // Live SSE Event Bus. All event handling lives in the reducer so it can be
 // unit tested; this used to be an if-chain that silently skipped task.* events,
 // leaving vault-watcher task edits invisible until the view remounted.
 //
 // The ref carries the reducer's input so the effect does not re-subscribe on
 // every state change (which would thrash the EventSource). It is refreshed on
 // each render, and the reducer's output is pushed straight into the setters
 // below, so the two stay in step.
 const serverState = useRef<ServerState>({
  ...emptyServerState(),
  notes,
  liveApp,
  whisper: whisperProgress as unknown as Record<string, unknown> | null,
  timelineKey,
  tasksKey,
  collectionsKey,
  embedding: null,
 });
 serverState.current = {
  ...serverState.current,
  notes,
  liveApp,
  whisper: whisperProgress as unknown as Record<string, unknown> | null,
  timelineKey,
  tasksKey,
  collectionsKey,
  embedding,
 };

 useEffect(() => {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => {
   let parsed: { type?: string; data?: unknown };
   try {
    parsed = JSON.parse(e.data);
   } catch {
    return; // malformed frame — ignore
   }
   const before = serverState.current;
   const next = applyServerEvent(before, parsed);
   serverState.current = next;
   if (next.notes !== before.notes) setNotes(next.notes as Note[]);
   if (next.liveApp !== before.liveApp) setLiveApp(next.liveApp);
   if (next.whisper !== before.whisper)
    setWhisperProgress(next.whisper as WhisperProgress | null);
   if (next.timelineKey !== before.timelineKey) setTimelineKey(next.timelineKey);
   if (next.tasksKey !== before.tasksKey) setTasksKey(next.tasksKey);
   if (next.collectionsKey !== before.collectionsKey) setCollectionsKey(next.collectionsKey);
   if (next.embedding !== before.embedding) {
    setEmbedding(next.embedding);
    // the finished marker means the button should re-enable and health is stale
    const done = next.embedding?.finished === true;
    if (done) {
     setBackfillBusy(false);
     void refreshStats();
    } else if (next.embedding?.started === true) {
     setBackfillBusy(true);
    }
   }
   if (next.refreshStats) refreshStats();
   if (next.toast) toast(next.toast);
  };
  es.onerror = () => {
   // EventSource reconnects on its own, but silently — surface it, or a
   // restarted backend leaves the inbox stale with no indication why.
   setStreamDown(true);
  };
  es.onopen = () => setStreamDown(false);
  return () => es.close();
 }, [refreshStats, toast]);

 // Global Desktop Keyboard Shortcuts
 useEffect(() => {
  function onKey(e: KeyboardEvent) {
   if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    setCmdOpen((open) => {
     const next = !open;
     if (next) {
      setCmdQuery("");
      setCmdIndex(0);
      setTimeout(() => cmdInputRef.current?.focus(), 20);
     }
     return next;
    });
    return;
   }
   if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
    e.preventDefault();
    setSidebarCollapsed((c) => !c);
    return;
   }
   if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "n") {
    e.preventDefault();
    captureRef.current?.focus();
    return;
   }

   const target = e.target as HTMLElement;
   const typing =
    target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
   if (e.key === "Escape") {
    if (cmdOpen) {
     setCmdOpen(false);
     return;
    }
    setSelectedId(null);
    (document.activeElement as HTMLElement)?.blur();
    return;
   }
   if (typing || cmdOpen) return;
   if (e.key === "n") {
    e.preventDefault();
    captureRef.current?.focus();
   } else if (e.key === "/") {
    e.preventDefault();
    setView("search");
    setTimeout(() => searchRef.current?.focus(), 30);
   } else if (e.key === "i") setView("inbox");
   else if (e.key === "t") setView("tasks");
   else if (e.key === "a") setView("assistant");
   else if (e.key === "l") setView("timeline");
   else if (e.key === "r") setView("reports");
   else if (e.key === "s") setView("settings");
    else if (e.key === "p") setView("processes");
   else if (e.key === "d") setView("dictation");
  }
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
 }, [cmdOpen]);

 async function pin(id: string) {
  try {
   mergeNote(await api.pinNote(id));
  } catch (e) {
   toast(e instanceof Error ? e.message : String(e), "err");
  }
 }

 async function star(id: string) {
  try {
   mergeNote(await api.starNote(id));
  } catch (e) {
   toast(e instanceof Error ? e.message : String(e), "err");
  }
 }

 const selected = notes.find((n) => n.id === selectedId) ?? null;

 const failedCount = useMemo(
  () => notes.filter((n) => n.status === "failed" && !n.trashed_at).length,
  [notes],
 );
 const inFlightCount = useMemo(
  () => notes.filter((n) => (n.status === "pending" || n.status === "processing") && !n.trashed_at).length,
  [notes],
 );

 const nonEmptyNotesCount = useMemo(
  () =>
   notes.filter(
    (n) =>
     !n.trashed_at &&
     !(
      n.status === "failed" &&
      !n.title.trim() &&
      !n.raw_text.trim() &&
      !n.summary.trim()
     ),
   ).length,
  [notes],
 );

 const navItems: Array<{
  id: View;
  label: string;
  icon: React.ReactNode;
  badge?: number;
  badgeWarn?: boolean;
  hint: string;
 }> = [
  {
   id: "inbox",
   label: "Inbox",
   icon: <TextIcon className="h-4 w-4" />,
   badge: failedCount || nonEmptyNotesCount || undefined,
   badgeWarn: failedCount > 0,
   hint: "i",
  },
  {
   id: "assistant",
   label: "Ask Fleeting",
   hint: "A",
   icon: <BotIcon className="h-4 w-4 text-ember-400" />,
  },
  { id: "timeline", label: "Timeline", icon: <ActivityIcon className="h-4 w-4" />, hint: "l" },
  { id: "reports", label: "Reports", icon: <FileIcon className="h-4 w-4" />, hint: "r" },
  {
   id: "tasks",
   label: "Tasks",
   icon: <TaskIcon className="h-4 w-4" />,
   badge: stats?.open_tasks || undefined,
   hint: "t",
  },
     { id: "processes", label: "Processes", icon: <CpuIcon className="h-4 w-4" />, badge: inFlightCount || undefined, hint: "p" },
   { id: "dictation", label: "Dictation", icon: <MicIcon className="h-4 w-4" />, hint: "d" },
   { id: "search", label: "Search", icon: <SearchIcon className="h-4 w-4" />, hint: "/" },
  { id: "settings", label: "Settings", icon: <SettingsIcon className="h-4 w-4" />, hint: "s" },
 ];

 // Command Palette Items
 const commandItems = useMemo(() => {
  const actions: Array<{
   id: string;
   title: string;
   sub: string;
   icon: React.ReactNode;
   shortcut?: string;
   run: () => void;
  }> = [
   {
    id: "act:capture",
    title: "Quick Capture Note / Task / YouTube URL",
    sub: "Focus top capture bar",
    icon: <SparkIcon className="h-4 w-4 text-ember-400" />,
    shortcut: "N",
    run: () => setTimeout(() => captureRef.current?.focus(), 20),
   },
   {
    id: "nav:inbox",
    title: "Go to Inbox Workbench",
    sub: `${nonEmptyNotesCount} active captures`,
    icon: <TextIcon className="h-4 w-4 text-ember-400" />,
    shortcut: "I",
    run: () => setView("inbox"),
   },
   {
    id: "act:assistant",
    title: "Ask Fleeting Assistant",
    sub: "Query personal notes, tasks, and daily logs",
    icon: <BotIcon className="h-4 w-4 text-ember-400" />,
    shortcut: "A",
    run: () => setView("assistant"),
   },
   {
    id: "nav:timeline",
    title: "Go to Activity & Timeline Studio",
    sub: `${fmtSecs(trackedToday)} tracked today`,
    icon: <ActivityIcon className="h-4 w-4 text-iris-400" />,
    shortcut: "L",
    run: () => setView("timeline"),
   },
   {
    id: "nav:tasks",
    title: "Go to Action Items & Tasks",
    sub: `${stats?.open_tasks ?? 0} open · ${stats?.done_tasks ?? 0} completed`,
    icon: <TaskIcon className="h-4 w-4 text-emerald-400" />,
    shortcut: "T",
    run: () => setView("tasks"),
   },
   {
    id: "nav:search",
    title: "Full-Text Knowledge Search (FTS5)",
    sub: "Search across titles, transcripts, summaries, and tags",
    icon: <SearchIcon className="h-4 w-4 text-cyan-400" />,
    shortcut: "/",
    run: () => {
     setView("search");
     setTimeout(() => searchRef.current?.focus(), 30);
    },
   },
   {
    id: "nav:processes",
    title: "System Processes & Active Apps",
    sub: "Monitor CPU, memory, and running applications",
    icon: <CpuIcon className="h-4 w-4 text-emerald-400" />,
    shortcut: "P",
    run: () => setView("processes"),
   },
   {
    id: "nav:settings",
    title: "Open System Preferences & Control Center",
    sub: "Configure Local LLM, Whisper, App Rules, and Vault",
    icon: <SettingsIcon className="h-4 w-4 text-ink-300" />,
    shortcut: "S",
    run: () => setView("settings"),
   },
   {
    id: "act:digest",
    title: "Generate Today's AI Activity Digest",
    sub: "Synthesize active window sessions, modified files & git commits",
    icon: <BotIcon className="h-4 w-4 text-iris-400" />,
    run: async () => {
     setView("timeline");
     toast("generating today's AI digest…");
     try {
      const d = new Date();
      const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      await api.generateDailyLog(day, true);
      setTimelineKey((k) => k + 1);
      toast("daily AI digest updated");
     } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
     }
    },
   },
   {
    id: "act:sidebar",
    title: "Toggle Sidebar Rail",
    sub: sidebarCollapsed ? "Expand navigation sidebar" : "Collapse sidebar to icon rail",
    icon: <TerminalIcon className="h-4 w-4 text-ink-300" />,
    shortcut: "Ctrl+B",
    run: () => setSidebarCollapsed((c) => !c),
   },
   {
    id: "act:llm",
    title: "Probe Local LLM Connection",
    sub: "Test Ollama / LM Studio availability",
    icon: <CpuIcon className="h-4 w-4 text-ember-400" />,
    run: async () => {
     try {
      const r = await api.testLLM();
      toast(
       r.ok
        ? `LLM connected (${(r.models ?? []).length} models)`
        : r.detail ?? "LLM unreachable",
       r.ok ? "ok" : "err",
      );
     } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
     }
    },
   },
   {
    id: "act:whisper",
    title: "Warm Up Whisper Speech-to-Text Model",
    sub: "Pre-load faster-whisper into RAM",
    icon: <MicIcon className="h-4 w-4 text-iris-400" />,
    run: async () => {
     toast("warming up Whisper model…");
     try {
      const r = await api.testWhisper();
      toast(`Whisper '${r.model}' ready in RAM`);
     } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "err");
     }
    },
   },
  ];

  const noteItems = notes.slice(0, 25).map((n) => ({
   id: `note:${n.id}`,
   title: n.title || n.raw_text.slice(0, 60) || "Untitled capture",
   sub: `Note · ${n.type} · ${n.tags.map((t) => `#${t}`).join(" ")}`,
   icon: <TextIcon className="h-4 w-4 text-ink-400" />,
   shortcut: "Open",
   run: () => setSelectedId(n.id),
  }));

  const all = [...actions, ...noteItems];
  const q = cmdQuery.trim().toLowerCase();
  if (!q) return all.slice(0, 12);
  return all
   .filter((it) => it.title.toLowerCase().includes(q) || it.sub.toLowerCase().includes(q))
   .slice(0, 14);
 }, [notes, nonEmptyNotesCount, stats, trackedToday, sidebarCollapsed, cmdQuery, toast]);

 const renderPortal = (node: React.ReactNode) => {
  if (typeof document !== "undefined" && document.body) {
   return createPortal(node, document.body);
  }
  return node;
 };

 return (
  <div data-view={view} className="app-root relative z-10 flex h-screen w-screen flex-col overflow-hidden bg-ink-950">
   {/* ==================== NATIVE ELECTRON TITLEBAR ==================== */}
   <header className="titlebar-drag flex h-14 shrink-0 items-center border-b border-ink-800 bg-ink-950 select-none">
    {/* Left App Identity & Sidebar Collapse Button */}
    <div
     className={`flex h-full shrink-0 items-center border-r border-ink-800 transition-[width,padding] duration-200 ease-out ${
      sidebarCollapsed ? "w-[60px] justify-center px-2" : "w-[216px] gap-2.5 px-3.5"
     }`}
    >
     <button
      onClick={() => setSidebarCollapsed((c) => !c)}
      className="brand-orb titlebar-nodrag flex h-8 w-8 shrink-0 items-center justify-center transition-transform hover:scale-105"
      title={sidebarCollapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"}
     >
      <FleetingMark className="h-7 w-7" />
     </button>
     {!sidebarCollapsed && (
      <>
       <div className="min-w-0">
        <span className="font-display text-[15px] font-bold tracking-tight text-ink-100">
         Fleeting
        </span>
       </div>
       <span className="studio-badge ml-auto rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-wider">
        {isElectron ? "STUDIO" : "LOCAL"}
       </span>
       <button
        onClick={() => setSidebarCollapsed(true)}
        className="titlebar-nodrag flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink-400 transition-colors hover:bg-ink-850 hover:text-ink-100"
        title="Collapse sidebar (Ctrl+B)"
        aria-label="Collapse sidebar"
       >
        <svg
         className="h-3.5 w-3.5"
         viewBox="0 0 16 16"
         fill="none"
         stroke="currentColor"
         strokeWidth="1.6"
         strokeLinecap="round"
         strokeLinejoin="round"
        >
         <rect x="2" y="2.5" width="12" height="11" rx="2" />
         <path d="M6 2.5v11M10.5 6.25 8.75 8l1.75 1.75" />
        </svg>
       </button>
      </>
     )}
    </div>

    {/* Center Quick Capture Bar + Command Palette Trigger */}
    <div className="flex min-w-0 flex-1 items-center justify-center gap-2.5 px-4">
     <div className="titlebar-nodrag min-w-0 flex-1 max-w-2xl">
      <CaptureBar
       inputRef={captureRef}
       onCapturedTask={() => {
        refreshStats();
        setTasksKey((k) => k + 1);
        toast("task captured", "ok", [{ label: "View", run: () => setView("tasks") }]);
       }}
       onCaptured={(n) => {
        mergeNote(n);
        refreshStats();
        setSelectedId(n.id);
        toast("captured — enriching in background", "ok", [
         { label: "View", run: () => setSelectedId(n.id) },
         {
          label: "Undo",
          run: () => {
           void api.deleteNote(n.id).then(
            () => {
             removeNote(n.id);
             toast("undone");
            },
            (e) => toast(e instanceof Error ? e.message : String(e), "err"),
           );
          },
         },
        ]);
       }}
       onError={(m) => toast(m, "err")}
      />
     </div>

     <button
      onClick={() => {
       setCmdOpen(true);
       setCmdQuery("");
       setCmdIndex(0);
       setTimeout(() => cmdInputRef.current?.focus(), 20);
      }}
      className="titlebar-nodrag hidden h-8 shrink-0 items-center gap-2 rounded-xl border px-3 text-xs transition-colors lg:flex"
      title="Open Command Palette (Ctrl+K)"
     >
      <SearchIcon className="h-3.5 w-3.5 text-ember-400" />
      <span>Commands</span>
      <kbd className="rounded-md border px-1.5 py-0.5 font-mono text-[9.5px]">
       Ctrl+K
      </kbd>
     </button>
    </div>

    {/* Right Telemetry Pill & Native Electron Window Controls */}
    <div className="titlebar-nodrag flex h-full shrink-0 items-center gap-1.5 pr-2.5 pl-2">
     <button
      onClick={() => setView("timeline")}
      className="hidden h-8 items-center gap-2 rounded-xl border border-ink-700 bg-ink-900 px-3 text-xs text-ink-200 transition-colors hover:border-ink-600 hover:bg-ink-850 md:flex"
      title="Open Activity Timeline"
     >
      <span
       className={`h-2 w-2 shrink-0 rounded-full ${
        liveApp ? "bg-emerald-400 pulse-dot" : "bg-ink-500"
       }`}
      />
      <span className="font-mono font-semibold tabular-nums text-ember-400">
       {fmtSecs(trackedToday)}
      </span>
      {liveApp && (
       <>
        <span className="text-ink-500">·</span>
        <span className="max-w-28 truncate font-mono text-[11px] text-ink-300">
         {prettyAppName(liveApp)}
        </span>
       </>
      )}
     </button>

     {/* Frameless Electron Window Control Buttons */}
     {isElectron && desktop && (
      <>
       <div className="mx-1 hidden h-5 w-px bg-ink-700 md:block" />
       <div className="flex items-center gap-0.5 rounded-xl border border-ink-700 bg-ink-900/90 p-0.5">
        <button
         onClick={() => void desktop.minimize()}
         className="flex h-7 w-8 items-center justify-center rounded-lg text-ink-400 transition-colors hover:bg-ink-850 hover:text-ink-100"
         title="Minimize"
         aria-label="Minimize window"
        >
         <svg
          className="h-3.5 w-3.5"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
         >
          <path d="M4 8.5h8" />
         </svg>
        </button>
        <button
         onClick={() => void desktop.toggleMaximize()}
         className="flex h-7 w-8 items-center justify-center rounded-lg text-ink-400 transition-colors hover:bg-ink-850 hover:text-ink-100"
         title={isMaximized ? "Restore" : "Maximize"}
         aria-label="Maximize window"
        >
         {isMaximized ? (
          <svg
           className="h-3.5 w-3.5"
           viewBox="0 0 16 16"
           fill="none"
           stroke="currentColor"
           strokeWidth="1.5"
          >
           <rect x="3.5" y="5.5" width="7" height="7" rx="1.2" />
           <path d="M5.5 5.5V4.2a1 1 0 0 1 1-1h5.3a1 1 0 0 1 1 1v5.3a1 1 0 0 1-1 1H10.5" />
          </svg>
         ) : (
          <svg
           className="h-3.5 w-3.5"
           viewBox="0 0 16 16"
           fill="none"
           stroke="currentColor"
           strokeWidth="1.5"
          >
           <rect x="3.75" y="3.75" width="8.5" height="8.5" rx="1.5" />
          </svg>
         )}
        </button>
        <button
         onClick={() => void desktop.close()}
         className="flex h-7 w-8 items-center justify-center rounded-lg text-ink-400 transition-colors hover:bg-red-500 hover:text-white"
         title="Close"
         aria-label="Close window"
        >
         <XIcon className="h-3.5 w-3.5" />
        </button>
       </div>
      </>
     )}
    </div>
   </header>

   {/* ==================== 3-PANE DESKTOP WORKBENCH ==================== */}
   <div className="flex min-h-0 flex-1 overflow-hidden">
    {/* Left Docked Sidebar / Activity Rail */}
    <nav
     className={`flex shrink-0 flex-col justify-between border-r border-ink-800 bg-ink-950 transition-[width] duration-200 ease-out ${
      sidebarCollapsed ? "w-[60px]" : "w-[216px]"
     }`}
    >
     <div className={sidebarCollapsed ? "px-2 py-3" : "p-2.5"}>
      {!sidebarCollapsed && (
       <p className="micro-label mb-1.5 px-2.5 !text-[9px]">Workspace</p>
      )}
      <ul className="space-y-1">
       {navItems.map((item) => {
        const active = view === item.id;
        return (
         <li key={item.id}>
          <button
           onClick={() => setView(item.id)}
           title={`${item.label} (${item.hint.toUpperCase()})`}
           className={`group relative flex items-center text-xs transition-all ${
            sidebarCollapsed
             ? "mx-auto h-10 w-10 justify-center px-0"
             : "w-full gap-2.5 px-3 py-2"
           } ${
            active
             ? "font-semibold"
             : ""
           }`}
          >
           {active && (
            <span
             className={`nav-bar-in absolute top-2 bottom-2 left-0 w-[3px] rounded-r bg-ember-400 shadow-[0_0_8px_rgb(240_157_115/0.5)]`}
            />
           )}
           <span className="shrink-0">
            {item.icon}
           </span>
           {sidebarCollapsed ? (
            item.badge !== undefined &&
            item.badge > 0 && (
             <span className={`absolute top-1 right-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full px-1 font-mono text-[8.5px] font-bold leading-none text-ink-100 ${item.badgeWarn ? "bg-red-500" : "bg-ember-500"}`}>
              {item.badge > 99 ? "99+" : item.badge}
             </span>
            )
           ) : (
            <>
             <span>{item.label}</span>
             {item.badge !== undefined && item.badge > 0 && (
              <span
               className={`ml-auto rounded-md px-1.5 py-0.5 font-mono text-[10px] leading-none ${
                item.badgeWarn
                 ? "bg-red-500/20 font-semibold text-red-300"
                 : active
                   ? "bg-ember-500/30 font-semibold text-ember-300"
                   : "bg-ink-900 text-ink-400"
               }`}
              >
               {item.badge}
              </span>
             )}
             {!active && item.hint && !item.badge && (
              <kbd className="ml-auto hidden rounded border border-ink-700 bg-ink-900 px-1 font-mono text-[9px] text-ink-400 group-hover:inline">
               {item.hint}
              </kbd>
             )}
            </>
           )}
          </button>
         </li>
        );
       })}
      </ul>
     </div>

     {/* Docked Sidebar Bottom Mini-Telemetry Panel */}
     {!sidebarCollapsed ? (
      <div className="p-2.5">
       <div className="glass space-y-2.5 rounded-2xl p-3">
        <button
         onClick={() => setView("timeline")}
         className="group w-full text-left"
         title="Open Activity Timeline"
        >
         <div className="flex items-center justify-between text-[10px]">
          <span className="micro-label !text-[9px]">7d Rhythm</span>
          <span className="font-mono font-semibold text-ember-400 group-hover:underline">
           {fmtSecs(trackedToday)}
          </span>
         </div>
         <div className="mt-1.5">
          <Spark data={week} color="#8fa876" width={168} height={28} />
         </div>
        </button>

        <div className="grid grid-cols-2 gap-1.5 border-t border-ink-700 pt-2">
         <button
          onClick={() => setView("inbox")}
          className="rounded-xl border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-left transition-colors hover:border-ink-600 hover:bg-ink-850"
         >
          <p className="text-[9px] font-semibold tracking-wider text-ink-400 uppercase">
           Captures
          </p>
          <p className="mt-0.5 font-mono text-xs font-bold text-ink-100">
           {nonEmptyNotesCount}
          </p>
         </button>
         <button
          onClick={() => setView("tasks")}
          className="rounded-xl border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-left transition-colors hover:border-ink-600 hover:bg-ink-850"
         >
          <p className="text-[9px] font-semibold tracking-wider text-ink-400 uppercase">
           Done
          </p>
          <p className="mt-0.5 font-mono text-xs font-bold text-emerald-400">
           {stats?.done_tasks ?? 0}
          </p>
         </button>
        </div>
       </div>
      </div>
     ) : (
      <div className="flex flex-col items-center gap-2 border-t border-ink-800 px-1.5 py-2.5">
       <button
        onClick={() => setView("timeline")}
        className="flex w-full flex-col items-center gap-1 rounded-xl border border-ink-700 bg-ink-900 py-1.5 text-[9.5px] font-mono font-semibold text-ember-400 transition-colors hover:border-ink-600 hover:bg-ink-850"
        title={`Tracked today: ${fmtSecs(trackedToday)} — Open Timeline`}
       >
        <span
         className={`h-1.5 w-1.5 rounded-full ${
          liveApp ? "bg-emerald-400 pulse-dot" : "bg-ink-500"
         }`}
        />
        <span className="tabular-nums">{fmtSecs(trackedToday)}</span>
       </button>
       <button
        onClick={() => setSidebarCollapsed(false)}
        className="flex h-9 w-9 items-center justify-center rounded-xl text-ink-400 transition-colors hover:bg-ink-850 hover:text-ink-100"
        title="Expand sidebar (Ctrl+B)"
        aria-label="Expand sidebar"
       >
        <svg
         className="h-4 w-4"
         viewBox="0 0 16 16"
         fill="none"
         stroke="currentColor"
         strokeWidth="1.6"
         strokeLinecap="round"
         strokeLinejoin="round"
        >
         <rect x="2" y="2.5" width="12" height="11" rx="2" />
         <path d="M6 2.5v11M8.75 6.25 10.5 8l-1.75 1.75" />
        </svg>
       </button>
      </div>
     )}
    </nav>

    {/* Center Main Workspace Pane */}
    <main key={view} className="page-main flex h-full min-w-0 flex-1 flex-col overflow-hidden">
     {view === "inbox" &&
      (loading ? (
       <div className="space-y-2.5 p-5">
        {[0, 1, 2, 3].map((i) => (
         <div key={i} className="shimmer h-20 rounded-2xl" />
        ))}
       </div>
      ) : (
       <Inbox
        refreshNotes={refetchNotes}
        notes={notes}
        selectedId={selectedId}
        onOpen={setSelectedId}
        onPin={pin}
        onStar={star}
        onQuickStart={() => captureRef.current?.focus()}
        collectionsKey={collectionsKey}
        onNoteUpdated={(n) => {
         mergeNote(n);
         refreshStats();
        }}
        onNoteDeleted={removeNote}
       />
      ))}
     {view === "timeline" && <TimelineView onToast={toast} refreshKey={timelineKey} />}
     {view === "reports" && <ReportsView onToast={toast} refreshKey={timelineKey} />}
     {view === "tasks" && (
      <TasksView
       refreshKey={tasksKey}
       onOpenNote={setSelectedId}
       onToast={toast}
       onTasksChanged={() => {
        refreshStats();
        setTasksKey((k) => k + 1);
       }}
      />
     )}
     {view === "search" && (
      <SearchView
       notes={notes}
       focusRef={searchRef}
       selectedId={selectedId}
       onOpen={setSelectedId}
       onPin={pin}
       onNoteUpdated={(n) => {
        mergeNote(n);
        refreshStats();
       }}
       onNoteDeleted={removeNote}
        onToast={toast}
      />
     )}
     {view === "processes" && (
      <ProcessesView onToast={toast} />
     )}
     {view === "dictation" && <DictationView notes={notes} onToast={toast} />}
     {view === "settings" && (
      <SettingsView
       onToast={toast}
       whisperProgress={whisperProgress}
       embeddingProgress={embedding}
       backfillBusy={backfillBusy}
      />
     )}
     {view === "assistant" && (
      <AssistantView
       onOpenNote={setSelectedId}
       onOpenTasks={() => setView("tasks")}
       onToast={toast}
      />
     )}
    </main>

    {/* Right Docked Split-Pane Inspector (when a note is selected) */}
    {selected && (
     <NoteDrawer
      note={selected}
      onClose={() => setSelectedId(null)}
      onUpdate={mergeNote}
      onDelete={removeNote}
      onOpenNote={setSelectedId}
      onToast={toast}
     />
    )}
   </div>

   {/* ==================== BOTTOM DESKTOP STATUS BAR ==================== */}
   <footer className="flex h-6 shrink-0 items-center justify-between border-t border-ink-800/80 bg-ink-900/90 px-3.5 font-mono text-[10.5px] text-ink-400">
    <div className="flex items-center gap-3">
     <span className="flex items-center gap-1.5 text-ink-300">
      <span className="h-1.5 w-1.5 rounded-full bg-ember-400" />
      {isElectron ? "Electron Studio" : "Local Engine"}
     </span>
     <span className="text-ink-700">|</span>
     <span className="flex items-center gap-1.5">
      <span
       className={`h-1.5 w-1.5 rounded-full ${
        liveApp ? "bg-emerald-400" : "bg-ink-600"
       }`}
      />
      {liveApp ? `focused: ${prettyAppName(liveApp)}` : "idle"}
     </span>
     <span className="text-ink-700">|</span>
     <span className="flex items-center gap-1">
      <ClockIcon className="h-3 w-3 text-ink-500" />
      {fmtSecs(trackedToday)} today
     </span>
     {streamDown && (
      <>
       <span className="text-ink-700">|</span>
       <span
        role="status"
        className="flex items-center gap-1.5 text-amber-300"
        title="Live updates are disconnected. The app reconnects automatically; the view may be stale until then."
       >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
        live updates offline
       </span>
      </>
     )}
     {stats && stats.queue > 0 && (
      <>
       <span className="text-ink-700">|</span>
       <span className="flex items-center gap-1.5 text-ember-300">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ember-400" />
        processing {stats.queue}…
       </span>
      </>
     )}
     {whisperProgress &&
      (whisperProgress.status === "downloading" ||
       whisperProgress.status === "loading") && (
       <>
        <span className="text-ink-700">|</span>
        <button
         onClick={() => setView("settings")}
         className="flex items-center gap-2 text-iris-300 hover:text-iris-200"
         title={whisperProgress.detail}
        >
         <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-iris-400" />
         <span>
          whisper ({whisperProgress.model}):{" "}
          {whisperProgress.status === "downloading"
           ? `downloading ${whisperProgress.percent}%`
           : "loading RAM…"}
         </span>
         <span className="inline-block h-1.5 w-16 overflow-hidden rounded-full bg-ink-800">
          <span
           className="block h-full bg-iris-400 transition-all duration-200"
           style={{ width: `${Math.max(4, whisperProgress.percent)}%` }}
          />
         </span>
        </button>
       </>
      )}
    </div>

    <div className="hidden items-center gap-3 sm:flex">
     <button onClick={() => setCmdOpen(true)} className="hover:text-ink-100">
      <strong className="text-ink-300">Ctrl+K</strong> palette
     </button>
     <span className="text-ink-700">·</span>
     <span>
      <strong className="text-ink-300">Ctrl+B</strong> sidebar ·{" "}
      <strong className="text-ink-300">n</strong> capture ·{" "}
      <strong className="text-ink-300">i/a/t///s</strong> views
     </span>
    </div>
   </footer>

   {/* ==================== COMMAND PALETTE MODAL (Ctrl+K) ==================== */}
   {cmdOpen &&
    renderPortal(
     <div
      onClick={() => setCmdOpen(false)}
      className="fixed inset-0 z-[100] flex items-start justify-center bg-slate-900/40 p-4 pt-[14vh] backdrop-blur-sm transition-opacity"
     >
      <div
       onClick={(e) => e.stopPropagation()}
       className="glass-studio rise w-full max-w-xl overflow-hidden rounded-2xl border border-ink-700 shadow-2xl ring-1 ring-black/5"
      >
       <div className="flex items-center gap-3 border-b border-ink-800 bg-ink-950 px-4 py-3.5">
        <SearchIcon className="h-4 w-4 shrink-0 text-ember-400" />
        <input
         ref={cmdInputRef}
         value={cmdQuery}
         onChange={(e) => {
          setCmdQuery(e.target.value);
          setCmdIndex(0);
         }}
         onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
           e.preventDefault();
           setCmdIndex((i) => Math.min(i + 1, Math.max(commandItems.length - 1, 0)));
          } else if (e.key === "ArrowUp") {
           e.preventDefault();
           setCmdIndex((i) => Math.max(i - 1, 0));
          } else if (e.key === "Enter" && commandItems[cmdIndex]) {
           e.preventDefault();
           const item = commandItems[cmdIndex];
           setCmdOpen(false);
           item.run();
          } else if (e.key === "Escape") {
           setCmdOpen(false);
          }
         }}
         placeholder="Type a command, jump to a workspace, or open a note…"
         className="flex-1 bg-transparent text-sm text-ink-100 placeholder-ink-400 outline-none border-none focus:outline-none focus:ring-0"
        />
        <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
         Esc
        </kbd>
       </div>

       <div className="max-h-[340px] overflow-y-auto p-1.5 bg-ink-950">
        {commandItems.length === 0 ? (
         <p className="py-8 text-center text-xs text-ink-400">
          No matching commands or notes.
         </p>
        ) : (
         commandItems.map((item, idx) => {
          const active = idx === cmdIndex;
          return (
           <button
            key={item.id}
            onMouseEnter={() => setCmdIndex(idx)}
            onClick={() => {
             setCmdOpen(false);
             item.run();
            }}
            className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors cursor-pointer ${
             active ? "bg-ember-500/10 text-ink-100 ring-1 ring-ember-400/30" : "text-ink-300 hover:bg-ink-900"
            }`}
           >
            <span className={`shrink-0 ${active ? "text-ember-400" : "text-ink-400"}`}>{item.icon}</span>
            <div className="min-w-0 flex-1">
             <p className="truncate text-xs font-semibold text-ink-100">{item.title}</p>
             <p className="truncate text-[11px] text-ink-400">{item.sub}</p>
            </div>
            {item.shortcut && (
             <kbd className="shrink-0 rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
              {item.shortcut}
             </kbd>
            )}
           </button>
          );
         })
        )}
       </div>
      </div>
     </div>
    )}

   {/* Floating Toasts */}
   {renderPortal(
    <div className="pointer-events-none fixed bottom-9 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-1.5">
     {toasts.map((t) => (
      <div
       key={t.id}
       className={`rise pointer-events-auto relative overflow-hidden rounded-xl border px-3.5 py-1.5 text-xs shadow-xl backdrop-blur ${
        t.kind === "err"
         ? "border-red-500/40 bg-red-950/90 text-red-200"
         : "border-ink-700 bg-ink-900/95 text-ink-100"
       }`}
      >
       {t.message}
       {t.actions?.map((a) => (
        <button
         key={a.label}
         onClick={() => {
          a.run();
          setToasts((list) => list.filter((x) => x.id !== t.id));
         }}
         className="ml-2 rounded border border-current/30 px-1.5 py-0.5 text-[11px] font-medium hover:opacity-80"
        >
         {a.label}
        </button>
       ))}
       <span className="toast-timer absolute bottom-0 left-0 h-0.5 bg-current opacity-40" />
      </div>
     ))}
    </div>
   )}
  </div>
 );
}
