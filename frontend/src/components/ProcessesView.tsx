import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { canSignal, killBlockedReason } from "./processOwnership";
import HeaderSparkline from "./HeaderSparkline";
import type { ProcessApp, ProcessInfo, ProcessDetails } from "../types";
import {
  CpuIcon,
  EyeIcon,
  RefreshIcon,
  SearchIcon,
  XIcon,
} from "./Icons";

type Tab = "apps" | "processes";
type SortKey = "cpu" | "memory" | "name" | "pid";

interface ProcessesViewProps {
  onToast: (message: string, kind?: "ok" | "err") => void;
  /** Test seam: skip the fetch and render these rows instead. */
  initialProcesses?: ProcessInfo[];
  /** Test seam: the user the backend runs as. */
  serverUser?: string;
}

/* ── status dot color helper ──────────────────────────────────── */
function statusColor(s: string): string {
  switch (s) {
    case "running":
      return "bg-emerald-400";
    case "sleeping":
    case "idle":
    case "disk-sleep":
      return "bg-ink-500";
    case "zombie":
    case "stopped":
    case "dead":
      return "bg-red-400";
    default:
      return "bg-amber-400";
  }
}

/* ── format command array to readable string ──────────────────── */
function fmtCmd(cmd: string | string[]): string {
  if (Array.isArray(cmd)) return cmd.join(" ");
  return cmd || "—";
}

export default function ProcessesView({
  onToast,
  initialProcesses,
  serverUser: serverUserIn,
}: ProcessesViewProps) {
  const [tab, setTab] = useState<Tab>("apps");
  const [apps, setApps] = useState<ProcessApp[]>([]);
  const [procs, setProcs] = useState<ProcessInfo[]>(initialProcesses ?? []);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortKey>("cpu");
  const [limit, setLimit] = useState(100);
  const [filter, setFilter] = useState("");
  const [inspectPid, setInspectPid] = useState<number | null>(null);
  const [details, setDetails] = useState<ProcessDetails | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [killConfirm, setKillConfirm] = useState<number | null>(null);
  const [killing, setKilling] = useState<number | null>(null);
  // Fleeting runs as the desktop user and cannot signal root-owned processes.
  // Without this the table offered "End" on ~85% of rows and the only feedback
  // was a 403 after the click.
  const [serverUser, setServerUser] = useState(serverUserIn ?? "");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── data fetching ───────────────────────────────────────────── */
  const fetchApps = useCallback(() => {
    api
      .processApps()
      .then(setApps)
      .catch(() => {});
  }, []);

  const fetchProcs = useCallback(() => {
    api
      .processList({ sort_by: sortBy, limit })
      .then(setProcs)
      .catch(() => {});
  }, [sortBy, limit]);

  const refresh = useCallback(() => {
    if (tab === "apps") fetchApps();
    else fetchProcs();
  }, [tab, fetchApps, fetchProcs]);

  /* initial load */
  useEffect(() => {
    api.whoami().then((r) => setServerUser(r.user)).catch(() => {});
    setLoading(true);
    const fn = tab === "apps" ? api.processApps() : api.processList({ sort_by: sortBy, limit });
    fn.then((d) => {
      if (tab === "apps") setApps(d as ProcessApp[]);
      else setProcs(d as ProcessInfo[]);
    })
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
      .finally(() => setLoading(false));
  }, [tab, sortBy, limit]);

  /* auto-refresh every 5s */
  useEffect(() => {
    intervalRef.current = setInterval(refresh, 5000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refresh]);

  /* inspect details */
  useEffect(() => {
    if (inspectPid === null) {
      setDetails(null);
      return;
    }
    setDetailsLoading(true);
    api
      .processDetails(inspectPid)
      .then(setDetails)
      .catch(() => {
        onToast("Failed to load process details", "err");
        setInspectPid(null);
      })
      .finally(() => setDetailsLoading(false));
  }, [inspectPid]);

  /* ── kill handler ────────────────────────────────────────────── */
  async function handleKill(pid: number, force = false) {
    setKilling(pid);
    try {
      await api.processKill(pid, force);
      onToast(`Process ${pid} terminated`);
      setKillConfirm(null);
      setInspectPid(null);
      setTimeout(refresh, 400);
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setKilling(null);
    }
  }

  /* ── filtered processes ──────────────────────────────────────── */
  const q = filter.trim().toLowerCase();
  const filtered = q
    ? procs.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          String(p.pid).includes(q) ||
          (p.username || "").toLowerCase().includes(q),
      )
    : procs;

  const tabs: { id: Tab; label: string }[] = [
    { id: "apps", label: "Active Apps" },
    { id: "processes", label: "Active Processes" },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── header ───────────────────────────────────────────────── */}
      <div className="flex items-center justify-between border-b border-ink-800 px-6 py-4">
        <div className="flex items-center gap-3">
          <CpuIcon className="h-5 w-5 text-ember-400" />
          <h1 className="font-display text-lg font-bold text-ink-100">Processes</h1>
        </div>
        <button
          onClick={() => {
            refresh();
            onToast("Refreshed");
          }}
          className="flex h-8 items-center gap-1.5 rounded-xl border border-ink-700 bg-ink-900 px-3 text-xs text-ink-300 transition-colors hover:border-ink-600 hover:bg-ink-850 hover:text-ink-100"
        >
          <RefreshIcon className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {/* ── tab bar ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 border-b border-ink-800 px-6">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => {
              setTab(t.id);
              setInspectPid(null);
              setKillConfirm(null);
            }}
            className={`relative px-4 py-2.5 text-xs font-semibold transition-colors ${
              tab === t.id ? "text-ink-100" : "text-ink-400 hover:text-ink-200"
            }`}
          >
            {t.label}
            {tab === t.id && (
              <span className="absolute inset-x-0 bottom-0 h-[2px] rounded-t bg-ember-400" />
            )}
          </button>
        ))}

        {/* ── #254 Sparkline on list header ──────────────────────── */}
        {tab === "apps" && apps.length > 0 && (
          <div className="ml-auto hidden sm:flex items-center py-1">
            <HeaderSparkline
              data={apps.slice(0, 7).map((a) => ({
                label: a.name,
                value: Math.round(a.memory_mb),
              }))}
              color="sky"
              label="Top apps memory profile"
              unit="MB"
            />
          </div>
        )}

        {/* ── process tab controls ───────────────────────────────── */}
        {tab === "processes" && (
          <div className="ml-auto flex items-center gap-2">
            <div className="relative">
              <SearchIcon className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by name…"
                className="h-8 w-44 rounded-xl border border-ink-700 bg-ink-900 pl-8 pr-3 text-xs text-ink-100 placeholder-ink-500 outline-none transition-colors focus:border-ink-600 focus:ring-0"
              />
            </div>
            <div className="flex items-center gap-1 rounded-xl border border-ink-700 bg-ink-900 p-0.5 text-[10px]">
              {(["cpu", "memory", "name", "pid"] as SortKey[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setSortBy(k)}
                  className={`rounded-lg px-2 py-1 font-semibold uppercase transition-colors ${
                    sortBy === k
                      ? "bg-ink-800 text-ember-400"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {k}
                </button>
              ))}
            </div>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="h-8 rounded-xl border border-ink-700 bg-ink-900 px-2 text-xs text-ink-300 outline-none"
            >
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </div>
        )}
      </div>

      {/* ── content ──────────────────────────────────────────────── */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div key={tab} className="rise flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="space-y-2.5">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="shimmer h-16 rounded-2xl" />
              ))}
            </div>
          ) : tab === "apps" ? (
            /* ── ACTIVE APPS ────────────────────────────────────────── */
            apps.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-20 text-center">
                <CpuIcon className="h-8 w-8 text-ink-600" />
                <p className="text-sm text-ink-400">No active desktop apps detected</p>
                <p className="text-xs text-ink-500">
                  Windowed applications will appear here
                </p>
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {apps.map((app) => (
                  <div
                    key={app.pid}
                    className="glass group relative flex flex-col gap-2 rounded-2xl border border-ink-800 p-4 transition-colors hover:border-ink-700"
                  >
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor(app.status)}`} />
                          <p className="truncate text-sm font-semibold text-ink-100">{app.name}</p>
                        </div>
                        {app.window_title && (
                          <p className="mt-0.5 truncate pl-4 text-xs text-ink-400">{app.window_title}</p>
                        )}
                      </div>
                      {killConfirm === app.pid ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setKillConfirm(null)}
                            className="rounded-lg px-2 py-1 text-[10px] font-semibold text-ink-400 transition-colors hover:text-ink-200"
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleKill(app.pid)}
                            disabled={killing === app.pid || !canSignal(app, serverUser)}
                            title={
                              canSignal(app, serverUser)
                                ? "End this application"
                                : killBlockedReason(app, serverUser)
                            }
                            className="rounded-lg bg-red-500/20 px-2 py-1 text-[10px] font-semibold text-red-300 transition-colors hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            {killing === app.pid ? "Ending…" : "End"}
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setKillConfirm(app.pid)}
                          disabled={!canSignal(app, serverUser)}
                          className="shrink-0 rounded-lg p-1.5 text-ink-500 opacity-0 transition-all hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-30"
                          title={
                            canSignal(app, serverUser)
                              ? "End process"
                              : killBlockedReason(app, serverUser)
                          }
                        >
                          <XIcon className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>

                    <div className="flex items-center gap-3 border-t border-ink-800 pt-2">
                      <span className="text-[10px] font-semibold tracking-wider text-ink-500 uppercase">
                        PID
                      </span>
                      <span className="font-mono text-xs tabular-nums text-ink-300">{app.pid}</span>
                      <span className="text-ink-700">·</span>
                      <span className="text-[10px] font-semibold tracking-wider text-ink-500 uppercase">
                        CPU
                      </span>
                      <span className="font-mono text-xs tabular-nums text-ember-400">
                        {app.cpu_percent.toFixed(1)}%
                      </span>
                      <span className="text-ink-700">·</span>
                      <span className="text-[10px] font-semibold tracking-wider text-ink-500 uppercase">
                        MEM
                      </span>
                      <span className="font-mono text-xs tabular-nums text-iris-400">
                        {app.memory_mb} MB
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )
          ) : (
            /* ── ACTIVE PROCESSES TABLE ──────────────────────────────── */
            filtered.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-20 text-center">
                <SearchIcon className="h-8 w-8 text-ink-600" />
                <p className="text-sm text-ink-400">
                  {q ? "No processes match your filter" : "No processes found"}
                </p>
              </div>
            ) : (
              <div className="overflow-hidden rounded-2xl border border-ink-800">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-ink-800 bg-ink-900/60 text-[10px] font-semibold tracking-wider text-ink-400 uppercase">
                      <th className="px-3 py-2.5">PID</th>
                      <th className="px-3 py-2.5">Name</th>
                      <th className="px-3 py-2.5 text-right">CPU %</th>
                      <th className="px-3 py-2.5 text-right">Memory</th>
                      <th className="px-3 py-2.5">Status</th>
                      <th className="hidden px-3 py-2.5 lg:table-cell">User</th>
                      <th className="hidden px-3 py-2.5 xl:table-cell">Command</th>
                      <th className="px-3 py-2.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((p) => (
                      <tr
                        key={p.pid}
                        className={`rise border-b border-ink-800/50 transition-colors hover:bg-ink-900/50 ${
                          inspectPid === p.pid ? "bg-ink-900/40" : ""
                        }`}
                      >
                        <td className="px-3 py-2 font-mono tabular-nums text-ink-300">{p.pid}</td>
                        <td className="max-w-[160px] truncate px-3 py-2 font-semibold text-ink-100">
                          {p.name}
                        </td>
                        <td className="px-3 py-2 text-right font-mono tabular-nums text-ember-400">
                          {p.cpu_percent.toFixed(1)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono tabular-nums text-iris-400">
                          {p.memory_mb}
                        </td>
                        <td className="px-3 py-2">
                          <span className="flex items-center gap-1.5">
                            <span
                              className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusColor(p.status)}`}
                            />
                            <span className="text-ink-400">{p.status}</span>
                          </span>
                        </td>
                        <td className="hidden max-w-[100px] truncate px-3 py-2 text-ink-400 lg:table-cell">
                          {p.username}
                        </td>
                        <td className="hidden max-w-[220px] truncate px-3 py-2 font-mono text-[11px] text-ink-500 xl:table-cell">
                          {fmtCmd(p.command)}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() =>
                                setInspectPid(inspectPid === p.pid ? null : p.pid)
                              }
                              className={`rounded-lg p-1.5 transition-colors ${
                                inspectPid === p.pid
                                  ? "bg-ember-500/20 text-ember-400"
                                  : "text-ink-500 hover:bg-ink-800 hover:text-ink-200"
                              }`}
                              title="Inspect"
                            >
                              <EyeIcon className="h-3.5 w-3.5" />
                            </button>
                            {killConfirm === p.pid ? (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => setKillConfirm(null)}
                                  className="rounded-lg px-2 py-1 text-[10px] font-semibold text-ink-400 transition-colors hover:text-ink-200"
                                >
                                  No
                                </button>
                                <button
                                  onClick={() => handleKill(p.pid)}
                                  disabled={killing === p.pid || !canSignal(p, serverUser)}
                                  className="rounded-lg bg-red-500/20 px-2 py-1 text-[10px] font-semibold text-red-300 transition-colors hover:bg-red-500/30 disabled:opacity-50"
                                >
                                  {killing === p.pid ? "…" : "End"}
                                </button>
                              </div>
                            ) : (
                              <button
                                onClick={() => setKillConfirm(p.pid)}
                                disabled={!canSignal(p, serverUser)}
                                title={
                                  canSignal(p, serverUser)
                                    ? "End process"
                                    : killBlockedReason(p, serverUser)
                                }
                                className="rounded-lg p-1.5 text-ink-500 transition-colors hover:bg-red-500/10 hover:text-red-400 disabled:cursor-not-allowed disabled:text-ink-700 disabled:hover:bg-transparent"
                              >
                                <XIcon className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>

        {/* ── inspect detail side-panel ───────────────────────────── */}
        {inspectPid !== null && (
          <div className="w-72 shrink-0 overflow-y-auto border-l border-ink-800 bg-ink-950 p-4">
            <div className="flex items-center justify-between">
              <p className="micro-label !text-[9px]">Process Details</p>
              <button
                onClick={() => setInspectPid(null)}
                className="rounded-lg p-1 text-ink-500 transition-colors hover:text-ink-200"
              >
                <XIcon className="h-3.5 w-3.5" />
              </button>
            </div>

            {detailsLoading ? (
              <div className="mt-4 space-y-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="shimmer h-6 rounded-xl" />
                ))}
              </div>
            ) : details ? (
              <div className="mt-3 space-y-3">
                <div className="rounded-xl border border-ink-800 bg-ink-900 p-3">
                  <p className="text-sm font-semibold text-ink-100">{details.name}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-ink-400">PID {details.pid}</p>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  {([
                    ["CPU", `${details.cpu_percent.toFixed(1)}%`, "text-ember-400"],
                    ["Memory", `${details.memory_mb} MB`, "text-iris-400"],
                    ["Threads", String(details.num_threads), "text-ink-200"],
                    ["Open Files", String(details.open_files_count), "text-ink-200"],
                    ["Connections", String(details.connections_count), "text-ink-200"],
                    ["Status", details.status, "text-ink-200"],
                  ] as const).map(([label, value, color]) => (
                    <div
                      key={label}
                      className="rounded-xl border border-ink-800 bg-ink-900 px-2.5 py-2"
                    >
                      <p className="text-[9px] font-semibold tracking-wider text-ink-500 uppercase">
                        {label}
                      </p>
                      <p className={`mt-0.5 font-mono text-xs font-bold tabular-nums ${color}`}>
                        {value}
                      </p>
                    </div>
                  ))}
                </div>

                {details.parent_pid !== null && (
                  <div className="rounded-xl border border-ink-800 bg-ink-900 px-3 py-2">
                    <p className="text-[9px] font-semibold tracking-wider text-ink-500 uppercase">
                      Parent PID
                    </p>
                    <p className="mt-0.5 font-mono text-xs text-ink-300">{details.parent_pid}</p>
                  </div>
                )}

                {details.children.length > 0 && (
                  <div className="rounded-xl border border-ink-800 bg-ink-900 px-3 py-2">
                    <p className="text-[9px] font-semibold tracking-wider text-ink-500 uppercase">
                      Children ({details.children.length})
                    </p>
                    <p className="mt-0.5 font-mono text-xs text-ink-300">
                      {details.children.join(", ")}
                    </p>
                  </div>
                )}

                <div className="rounded-xl border border-ink-800 bg-ink-900 px-3 py-2">
                  <p className="text-[9px] font-semibold tracking-wider text-ink-500 uppercase">
                    User
                  </p>
                  <p className="mt-0.5 text-xs text-ink-300">{details.username}</p>
                </div>

                <div className="rounded-xl border border-ink-800 bg-ink-900 px-3 py-2">
                  <p className="text-[9px] font-semibold tracking-wider text-ink-500 uppercase">
                    Command
                  </p>
                  <p className="mt-0.5 max-h-20 overflow-y-auto font-mono text-[11px] leading-relaxed text-ink-400 break-all">
                    {fmtCmd(details.command)}
                  </p>
                </div>

                <div className="pt-1">
                  <button
                    onClick={() => handleKill(details.pid, true)}
                    disabled={killing === details.pid}
                    className="w-full rounded-xl border border-red-500/30 bg-red-500/10 py-2 text-xs font-semibold text-red-300 transition-colors hover:bg-red-500/20 disabled:opacity-50"
                  >
                    {killing === details.pid ? "Terminating…" : "Force Kill (SIGKILL)"}
                  </button>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-xs text-ink-500">No details available</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
