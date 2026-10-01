import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { fmtSecs, prettyAppName } from "./apps";
import CaptureBar from "./components/CaptureBar";
import { Spark } from "./components/charts";
import Inbox from "./components/Inbox";
import NoteDrawer from "./components/NoteDrawer";
import SearchView from "./components/SearchView";
import SettingsView from "./components/SettingsView";
import TasksView from "./components/TasksView";
import TimelineView from "./components/TimelineView";
import {
  ActivityIcon,
  BotIcon,
  ClockIcon,
  CpuIcon,
  MicIcon,
  SearchIcon,
  SettingsIcon,
  SparkIcon,
  TaskIcon,
  TerminalIcon,
  TextIcon,
  XIcon,
} from "./components/Icons";
import type { Note, Stats, WhisperProgress } from "./types";

type View = "inbox" | "timeline" | "tasks" | "search" | "settings";

interface Toast {
  id: number;
  message: string;
  kind: "ok" | "err";
}

export default function App() {
  const [view, setView] = useState<View>("inbox");
  const [notes, setNotes] = useState<Note[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [loading, setLoading] = useState(true);
  const [trackedToday, setTrackedToday] = useState(0);
  const [liveApp, setLiveApp] = useState<string | null>(null);
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

  const desktop = typeof window !== "undefined" ? window.fleetingDesktop : undefined;
  const isElectron = Boolean(desktop?.isElectron);

  const toast = useCallback((message: string, kind: "ok" | "err" = "ok") => {
    const id = ++toastSeq.current;
    setToasts((t) => [...t, { id, message, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
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
        target === "tasks" ||
        target === "search" ||
        target === "settings"
      ) {
        setView(target);
      }
    });
    return () => {
      offMax();
      offNav();
    };
  }, [desktop]);

  // Live SSE Event Bus
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onmessage = (e) => {
      try {
        const { type, data } = JSON.parse(e.data);
        if (type === "note.created" || type === "note.updated") {
          mergeNote(data as Note);
          if ((data as Note).status === "done") refreshStats();
        }
        if (type === "note.deleted") removeNote(data.id);
        if (type === "activity.live") {
          const session = data.session as { app_class?: string } | null;
          setLiveApp(session?.app_class ?? null);
        }
        if (type === "whisper.progress") {
          setWhisperProgress(data as WhisperProgress);
        }
        if (type === "dailylog.updated") {
          setTimelineKey((k) => k + 1);
          if (data.kind === "daily-report") {
            toast(`Daily report for ${data.day} is ready`);
          }
        }
      } catch {
        /* ignore malformed events */
      }
    };
    return () => es.close();
  }, [mergeNote, removeNote, refreshStats, toast]);

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
      else if (e.key === "a") setView("timeline");
      else if (e.key === "s") setView("settings");
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

  const selected = notes.find((n) => n.id === selectedId) ?? null;

  const nonEmptyNotesCount = useMemo(
    () =>
      notes.filter(
        (n) =>
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
    hint: string;
  }> = [
    {
      id: "inbox",
      label: "Inbox",
      icon: <TextIcon className="h-4 w-4" />,
      badge: nonEmptyNotesCount || undefined,
      hint: "i",
    },
    { id: "timeline", label: "Timeline", icon: <ActivityIcon className="h-4 w-4" />, hint: "a" },
    {
      id: "tasks",
      label: "Tasks",
      icon: <TaskIcon className="h-4 w-4" />,
      badge: stats?.open_tasks || undefined,
      hint: "t",
    },
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
        id: "nav:timeline",
        title: "Go to Activity & Timeline Studio",
        sub: `${fmtSecs(trackedToday)} tracked today`,
        icon: <ActivityIcon className="h-4 w-4 text-iris-400" />,
        shortcut: "A",
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

  return (
    <div className="relative z-10 flex h-screen w-screen flex-col overflow-hidden bg-ink-950">
      {/* ==================== NATIVE ELECTRON TITLEBAR ==================== */}
      <header className="titlebar-drag flex h-14 shrink-0 items-center border-b border-[#354b3f] bg-[#23382e] select-none">
        {/* Left App Identity & Sidebar Collapse Button */}
        <div
          className={`flex h-full shrink-0 items-center border-r border-[#354b3f] transition-[width,padding] duration-200 ease-out ${
            sidebarCollapsed ? "w-[60px] justify-center px-2" : "w-[216px] gap-2.5 px-3.5"
          }`}
        >
          <button
            onClick={() => setSidebarCollapsed((c) => !c)}
            className="brand-orb titlebar-nodrag flex h-8 w-8 shrink-0 items-center justify-center transition-transform hover:scale-105"
            title={sidebarCollapsed ? "Expand sidebar (Ctrl+B)" : "Collapse sidebar (Ctrl+B)"}
          >
            <SparkIcon className="h-4 w-4" />
          </button>
          {!sidebarCollapsed && (
            <>
              <div className="min-w-0">
                <span className="font-display text-[15px] font-bold tracking-tight text-[#f4f0e7]">
                  Fleeting
                </span>
              </div>
              <span className="studio-badge ml-auto rounded-md border px-1.5 py-0.5 font-mono text-[9px] font-semibold tracking-wider">
                {isElectron ? "STUDIO" : "LOCAL"}
              </span>
              <button
                onClick={() => setSidebarCollapsed(true)}
                className="titlebar-nodrag flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[#9fb09e] transition-colors hover:bg-[#31493c] hover:text-[#f4f0e7]"
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
              onCaptured={(n) => {
                mergeNote(n);
                refreshStats();
                setSelectedId(n.id);
                toast("captured — enriching in background");
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
            <SearchIcon className="h-3.5 w-3.5 text-[#f09d73]" />
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
            className="hidden h-8 items-center gap-2 rounded-xl border border-[#465c4f] bg-[#2b4235] px-3 text-xs text-[#e6eadf] transition-colors hover:border-[#5e7869] hover:bg-[#344e40] md:flex"
            title="Open Activity Timeline"
          >
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${
                liveApp ? "bg-emerald-400 pulse-dot" : "bg-[#6c7d70]"
              }`}
            />
            <span className="font-mono font-semibold tabular-nums text-[#f4a97f]">
              {fmtSecs(trackedToday)}
            </span>
            {liveApp && (
              <>
                <span className="text-[#6c7d70]">·</span>
                <span className="max-w-28 truncate font-mono text-[11px] text-[#d5ddd0]">
                  {prettyAppName(liveApp)}
                </span>
              </>
            )}
          </button>

          {/* Frameless Electron Window Control Buttons */}
          {isElectron && desktop && (
            <>
              <div className="mx-1 hidden h-5 w-px bg-[#3b5245] md:block" />
              <div className="flex items-center gap-0.5 rounded-xl border border-[#3c5245] bg-[#1e3128]/90 p-0.5">
                <button
                  onClick={() => void desktop.minimize()}
                  className="flex h-7 w-8 items-center justify-center rounded-lg text-[#c2ccc0] transition-colors hover:bg-[#324b3d] hover:text-[#fffdf8]"
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
                  className="flex h-7 w-8 items-center justify-center rounded-lg text-[#c2ccc0] transition-colors hover:bg-[#324b3d] hover:text-[#fffdf8]"
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
                  className="flex h-7 w-8 items-center justify-center rounded-lg text-[#c2ccc0] transition-colors hover:bg-[#c84b31] hover:text-white"
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
          className={`flex shrink-0 flex-col justify-between border-r border-[#354b3f] bg-[#23382e] transition-[width] duration-200 ease-out ${
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
                          className={`absolute top-2 bottom-2 left-0 w-[3px] rounded-r bg-[#f09d73] shadow-[0_0_8px_rgb(240_157_115/0.5)]`}
                        />
                      )}
                      <span className="shrink-0">
                        {item.icon}
                      </span>
                      {sidebarCollapsed ? (
                        item.badge !== undefined &&
                        item.badge > 0 && (
                          <span className="absolute top-1 right-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-[#c8643b] px-1 font-mono text-[8.5px] font-bold leading-none text-[#fffdf8]">
                            {item.badge > 99 ? "99+" : item.badge}
                          </span>
                        )
                      ) : (
                        <>
                          <span>{item.label}</span>
                          {item.badge !== undefined && item.badge > 0 && (
                            <span
                              className={`ml-auto rounded-md px-1.5 py-0.5 font-mono text-[10px] leading-none ${
                                active
                                  ? "bg-[#c8643b]/30 font-semibold text-[#f7b391]"
                                  : "bg-[#1d3026] text-[#a5b3a1]"
                              }`}
                            >
                              {item.badge}
                            </span>
                          )}
                          {!active && item.hint && !item.badge && (
                            <kbd className="ml-auto hidden rounded border border-[#445b4d] bg-[#1d3026] px-1 font-mono text-[9px] text-[#9fb09e] group-hover:inline">
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
                    <span className="font-mono font-semibold text-[#f4a97f] group-hover:underline">
                      {fmtSecs(trackedToday)}
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <Spark data={week} color="#8fa876" width={168} height={28} />
                  </div>
                </button>

                <div className="grid grid-cols-2 gap-1.5 border-t border-[#3c5245] pt-2">
                  <button
                    onClick={() => setView("inbox")}
                    className="rounded-xl border border-[#43594c] bg-[#21342a] px-2.5 py-1.5 text-left transition-colors hover:border-[#5b7465] hover:bg-[#273d31]"
                  >
                    <p className="text-[9px] font-semibold tracking-wider text-[#9bb09a] uppercase">
                      Captures
                    </p>
                    <p className="mt-0.5 font-mono text-xs font-bold text-[#f4f0e7]">
                      {nonEmptyNotesCount}
                    </p>
                  </button>
                  <button
                    onClick={() => setView("tasks")}
                    className="rounded-xl border border-[#43594c] bg-[#21342a] px-2.5 py-1.5 text-left transition-colors hover:border-[#5b7465] hover:bg-[#273d31]"
                  >
                    <p className="text-[9px] font-semibold tracking-wider text-[#9bb09a] uppercase">
                      Done
                    </p>
                    <p className="mt-0.5 font-mono text-xs font-bold text-[#7fd1ae]">
                      {stats?.done_tasks ?? 0}
                    </p>
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 border-t border-[#354b3f] px-1.5 py-2.5">
              <button
                onClick={() => setView("timeline")}
                className="flex w-full flex-col items-center gap-1 rounded-xl border border-[#3e5447] bg-[#2a4034] py-1.5 text-[9.5px] font-mono font-semibold text-[#f4a97f] transition-colors hover:border-[#567060] hover:bg-[#31493c]"
                title={`Tracked today: ${fmtSecs(trackedToday)} — Open Timeline`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    liveApp ? "bg-emerald-400 pulse-dot" : "bg-[#6c7d70]"
                  }`}
                />
                <span className="tabular-nums">{fmtSecs(trackedToday)}</span>
              </button>
              <button
                onClick={() => setSidebarCollapsed(false)}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-[#b8c3b1] transition-colors hover:bg-[#31493c] hover:text-[#fffdf8]"
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
        <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
          {view === "inbox" &&
            (loading ? (
              <div className="space-y-2.5 p-5">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} className="shimmer h-20 rounded-2xl" />
                ))}
              </div>
            ) : (
              <Inbox
                notes={notes}
                selectedId={selectedId}
                onOpen={setSelectedId}
                onPin={pin}
                onQuickStart={() => captureRef.current?.focus()}
                onNoteUpdated={(n) => {
                  mergeNote(n);
                  refreshStats();
                }}
                onNoteDeleted={removeNote}
              />
            ))}
          {view === "timeline" && <TimelineView onToast={toast} refreshKey={timelineKey} />}
          {view === "tasks" && (
            <TasksView
              refreshKey={tasksKey}
              onOpenNote={setSelectedId}
              onToast={toast}
              onTasksChanged={() => {
                refreshStats();
                setTasksKey((k) => k + 1);
              }}
              onNoteCreated={(n) => {
                mergeNote(n);
                refreshStats();
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
            />
          )}
          {view === "settings" && (
            <SettingsView onToast={toast} whisperProgress={whisperProgress} />
          )}
        </main>

        {/* Right Docked Split-Pane Inspector (when a note is selected) */}
        {selected && (
          <NoteDrawer
            note={selected}
            onClose={() => setSelectedId(null)}
            onUpdate={mergeNote}
            onDelete={removeNote}
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
      {cmdOpen && (
        <div
          onClick={() => setCmdOpen(false)}
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/65 pt-20 backdrop-blur-xs"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="glass-studio rise w-full max-w-xl overflow-hidden rounded-2xl border border-ink-700 shadow-2xl"
          >
            <div className="flex items-center gap-2.5 border-b border-ink-800 px-4 py-3">
              <SearchIcon className="h-4 w-4 text-ember-400" />
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
                  }
                }}
                placeholder="Type a command, jump to a workspace, or open a note…"
                className="flex-1 bg-transparent text-sm text-ink-100 placeholder-ink-400 outline-none"
              />
              <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
                Esc
              </kbd>
            </div>

            <div className="max-h-80 overflow-y-auto p-1.5">
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
                      className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors ${
                        active ? "bg-ink-800 text-ink-100" : "text-ink-300 hover:bg-ink-850"
                      }`}
                    >
                      <span className="shrink-0">{item.icon}</span>
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
      <div className="pointer-events-none fixed bottom-9 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-1.5">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`rise rounded-xl border px-3.5 py-1.5 text-xs shadow-xl backdrop-blur ${
              t.kind === "err"
                ? "border-red-500/40 bg-red-950/90 text-red-200"
                : "border-ink-600 bg-ink-850/95 text-ink-100"
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}
