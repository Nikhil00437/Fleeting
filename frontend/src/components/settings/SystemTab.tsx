import {
  CheckIcon,
  CopyIcon,
  DatabaseIcon,
  RefreshIcon,
  TerminalIcon,
} from "../Icons";
import { type ToastFn } from "./shared";
import type { HealthStatus, Settings } from "../../types";

/** Diagnostics tab: /api/health telemetry and where the config lives. */
export default function SystemTab({
  health,
  s,
  onToast,
  loadAll,
}: {
  health: HealthStatus | null;
  s: Settings;
  onToast: ToastFn;
  /** Re-probes /api/health, /api/settings and /api/apps. */
  loadAll: () => void;
}) {
  const fmtUptime = (secs: number) => {
    if (!secs || secs < 0) return "—";
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${Math.floor(secs % 60)}s`;
  };

  return (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="glass-studio space-y-4 rounded-2xl p-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30">
                  <DatabaseIcon className="h-4.5 w-4.5" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-ink-100">
                    Runtime Telemetry & Health
                  </h2>
                  <p className="text-xs text-ink-400">Live backend diagnostics from /api/health</p>
                </div>
              </div>
              <button
                onClick={loadAll}
                className="flex items-center gap-1.5 rounded-xl border border-ink-700 bg-ink-900 px-3 py-1.5 text-xs text-ink-200 hover:border-ember-400/40"
              >
                <RefreshIcon className="h-3 w-3" /> Refresh
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Status</p>
                {/* health===null means the probe failed: say so, rather than
                    reporting "Degraded" for a server that is not answering. */}
                <p
                  className={`mt-1 flex items-center gap-1 font-mono text-xs font-bold ${
                    !health
                      ? "text-ink-300"
                      : health.ok && !health.degradations?.length
                        ? "text-emerald-300"
                        : "text-amber-300"
                  }`}
                >
                  {!health ? (
                    "Unreachable"
                  ) : health.ok && !health.degradations?.length ? (
                    <>
                      <CheckIcon className="h-3.5 w-3.5" /> Healthy
                    </>
                  ) : (
                    "Reduced"
                  )}
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Semantic search</p>
                <p className="mt-1 font-mono text-xs font-bold text-ink-100">
                  {health?.semantic_search === "semantic" ? "Semantic" : "Lexical only"}
                  {health?.stale_embeddings ? (
                    <span className="ml-1 text-[10px] font-normal text-amber-300">
                      {health.stale_embeddings} stale
                    </span>
                  ) : null}
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Uptime</p>
                <p className="mt-1 font-mono text-xs font-bold text-ink-100">
                  {health ? fmtUptime(health.uptime_secs) : "—"}
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Version</p>
                <p className="mt-1 font-mono text-xs font-bold text-ember-300">
                  v{health?.version ?? "0.1.0"}
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">SQLite WAL + FTS5</p>
                <p className="mt-1 font-mono text-xs font-bold text-ink-100">
                  {health?.db ? "Connected" : "Error"}
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Worker Queue</p>
                <p className="mt-1 font-mono text-xs font-bold text-ink-100">
                  {health?.queue ?? 0} pending
                </p>
              </div>
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3">
                <p className="micro-label !text-[9px]">Whisper Memory</p>
                <p className="mt-1 font-mono text-xs font-bold text-iris-300">
                  {health?.whisper_loaded ? "Warm in RAM" : "Lazy (On-Demand)"}
                </p>
              </div>
            </div>
          </section>

          <section className="glass-studio space-y-4 rounded-2xl p-5">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-iris-500/15 text-iris-300 ring-1 ring-iris-400/30">
                <TerminalIcon className="h-4.5 w-4.5" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-ink-100">
                  Server & Keyboard Shortcuts
                </h2>
                <p className="text-xs text-ink-400">
                  Local binding and application keybindings
                </p>
              </div>
            </div>

            <div className="space-y-3">
              {health?.degradations?.length ? (
                <div
                  role="status"
                  className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3.5"
                >
                  <p className="micro-label !text-[9px] !text-amber-300">
                    Running in a reduced mode
                  </p>
                  <ul className="mt-2 space-y-1.5 text-xs text-ink-200">
                    {health.degradations.map((d) => (
                      <li key={d} className="flex gap-1.5">
                        <span aria-hidden="true" className="text-amber-400">
                          •
                        </span>
                        <span>{d}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label !text-[9px]">TOML Configuration File</p>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <code className="selectable truncate font-mono text-xs text-ink-200">
                    {s.config_path}
                  </code>
                  <button
                    onClick={async () => {
                      await navigator.clipboard.writeText(s.config_path);
                      onToast("config path copied");
                    }}
                    className="flex shrink-0 items-center gap-1 rounded-lg border border-ink-700 px-2.5 py-1 text-[10.5px] text-ink-300 hover:border-ember-400/40 hover:text-ink-100"
                  >
                    <CopyIcon className="h-3 w-3" /> Copy
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label !text-[9px]">Bound Loopback Address</p>
                <p className="selectable mt-1 font-mono text-xs text-ink-200">
                  http://{s.host}:{s.port} <span className="text-ink-400">(local-only)</span>
                </p>
              </div>

              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label mb-2 !text-[9px]">Keyboard Shortcuts</p>
                <div className="grid grid-cols-2 gap-2 text-xs text-ink-300">
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      n
                    </kbd>{" "}
                    Focus Quick Capture
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      i
                    </kbd>{" "}
                    Inbox Pane
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      a
                    </kbd>{" "}
                    Timeline Pane
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      t
                    </kbd>{" "}
                    Tasks Pane
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      /
                    </kbd>{" "}
                    Search Pane
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      s
                    </kbd>{" "}
                    Settings Pane
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
  );
}
