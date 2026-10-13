import {
  CheckIcon,
  CopyIcon,
  DatabaseIcon,
  RefreshIcon,
  TerminalIcon,
} from "../Icons";
import { type ToastFn } from "./shared";
import { useEffect, useState } from "react";
import { api, type RuntimeMetrics } from "../../api";
import { errorMessage } from "../settingsState";
import { backfillProgress, describeBackfill } from "../backfill";
import ChartPalettePicker from "../ChartPalettePicker";
import type { HealthStatus, OfflineReport, PreflightReport, Settings } from "../../types";
import PreflightCard from "../PreflightCard";
import { combine, describeOffline, remoteStylesheets } from "../offline";

/** Diagnostics tab: /api/health telemetry and where the config lives. */
export default function SystemTab({
  health,
  s,
  onToast,
  loadAll,
  embedding,
  onBackfill,
  backfillBusy,
}: {
  health: HealthStatus | null;
  s: Settings;
  onToast: ToastFn;
  /** Re-probes /api/health, /api/settings and /api/apps. */
  loadAll: () => void;
  /** Latest embedding-migration payload from SSE. */
  embedding: Record<string, unknown> | null;
  onBackfill: () => void;
  backfillBusy: boolean;
}) {
  // #395: the bundle is gathered on click, not on mount — it tail-parses the
  // log, and nobody opens Settings to look at a bug report.
  const [diagBusy, setDiagBusy] = useState(false);
  // #390: fetched on mount rather than on click, unlike the diagnostics
  // bundle — unlike a bug report, this is a thing you glance at.
  const [metrics, setMetrics] = useState<RuntimeMetrics | null>(null);
  // #100. Fetched with the other mount-time probes rather than on click: the
  // question "what is missing?" is the first thing anyone opens Settings with.
  // `loadAll` is the refresh button's handle, so preflight re-runs with it.
  const [preflight, setPreflight] = useState<PreflightReport | null>(null);
  // #460. Read after paint: the font stylesheet is in `document.styleSheets` by
  // then, and reading it during render would miss it every time.
  const [remoteHrefs, setRemoteHrefs] = useState<string[]>([]);
  const [offlineReport, setOfflineReport] = useState<OfflineReport | null>(null);
  useEffect(() => {
    setRemoteHrefs(remoteStylesheets());
    api.offline().then(setOfflineReport).catch(() => {});
  }, []);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api
      .preflight()
      .then((p) => {
        if (live) {
          setPreflight(p);
          setPreflightError(null);
        }
      })
      .catch((e: unknown) => {
        // A silent failure here reads as "everything is fine", which is the
        // one reading that is never right.
        if (live) setPreflightError(errorMessage(e));
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    let live = true;
    api.runtimeMetrics(24).then((m) => {
      if (live) setMetrics(m);
    }).catch(() => {
      if (live) setMetrics(null);
    });
    return () => {
      live = false;
    };
  }, []);
  const fmtMs = (ms: number) =>
    ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
  const bf = embedding ? backfillProgress(embedding) : null;
  const bfMsg = describeBackfill(bf);
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
                  <p className="text-xs text-ink-400">
                    {/* #100 preflight sits first: if something is missing, the
                        telemetry below is a description of a broken app. */}
                    Missing dependencies, then live diagnostics from /api/health
                  </p>
                </div>
              </div>
              <button
                onClick={loadAll}
                className="flex items-center gap-1.5 rounded-xl border border-ink-700 bg-ink-900 px-3 py-1.5 text-xs text-ink-200 hover:border-ember-400/40"
              >
                <RefreshIcon className="h-3 w-3" /> Refresh
              </button>
            </div>

            <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
              <p className="micro-label !text-[9px]">Network</p>
              <p className="text-[11px] text-ink-200">
                {describeOffline(combine(offlineReport, remoteHrefs))}
              </p>
              <ul className="mt-1 space-y-0.5">
                {combine(offlineReport, remoteHrefs).map((f) => (
                  <li key={f.name} className="text-[10px] text-ink-500">
                    <span className={f.network === "remote" ? "text-amber-300" : ""}>{f.name}</span>
                    {" — "}
                    {f.detail}
                  </li>
                ))}
              </ul>
            </div>

            <PreflightCard checks={preflight?.checks ?? null} error={preflightError ?? undefined} />

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
                  {health.stale_embeddings ? (
                    <div className="mt-3 border-t border-amber-500/20 pt-3">
                      <button
                        onClick={onBackfill}
                        disabled={backfillBusy}
                        className="rounded-lg border border-amber-400/30 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25 disabled:opacity-50"
                      >
                        {backfillBusy ? "Re-embedding\u2026" : "Re-embed for semantic search"}
                      </button>
                      {bfMsg ? (
                        <p role="status" className="mt-2 font-mono text-[11px] text-ink-300">
                          {bfMsg}
                        </p>
                      ) : (
                        <p className="mt-2 text-[11px] text-ink-400">
                          Older notes stay out of semantic search until this runs.
                        </p>
                      )}
                      {bf && bf.percent !== null ? (
                        <div
                          role="progressbar"
                          aria-valuenow={bf.percent}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          className="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-800"
                        >
                          <div
                            className="h-full rounded-full bg-amber-400 transition-[width]"
                            style={{ width: `${bf.percent}%` }}
                          />
                        </div>
                      ) : null}
                    </div>
                  ) : null}
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
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label !text-[9px]">Last 24 hours</p>
                {metrics ? (
                  <>
                    <dl className="mt-2 grid grid-cols-3 gap-3 text-center">
                      {[
                        ["Captures", String(metrics.throughput.total)],
                        ["Median", fmtMs(metrics.enrichment.median_ms)],
                        ["Errors", `${(metrics.errors.rate * 100).toFixed(0)}%`],
                      ].map(([label, value]) => (
                        <div key={label}>
                          <dd className="font-mono text-lg leading-none text-ink-100">
                            {value}
                          </dd>
                          <dt className="mt-1 text-[10px] text-ink-400">{label}</dt>
                        </div>
                      ))}
                    </dl>
                    {/* A bar per hour with work in it. Absent hours are gaps, not
                        zeros: "nothing happened" and "nothing was measured" are
                        different claims. */}
                    <div className="mt-3 flex h-8 items-end gap-[2px]" role="img"
                      aria-label={`captures per hour, ${metrics.throughput.buckets.length} active hours`}>
                      {metrics.throughput.buckets.map((b) => (
                        <div
                          key={b.hour}
                          title={`${b.hour}: ${b.count}`}
                          className="flex-1 rounded-t bg-ember-500/60"
                          style={{
                            height: `${Math.max(
                              12,
                              (b.count / Math.max(...metrics.throughput.buckets.map((x) => x.count))) * 100,
                            )}%`,
                          }}
                        />
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="mt-1 text-[11px] text-ink-400">Not available.</p>
                )}
              </div>

                <p className="micro-label !text-[9px]">Diagnostics Bundle</p>
                <p className="mt-1 text-[11px] leading-relaxed text-ink-400">
                  Version, platform, your settings and the last few warnings —
                  everything needed to reproduce a bug. API keys, tokens and
                  passwords are replaced with <code className="font-mono">&lt;set&gt;</code>
                  before anything leaves the backend.
                </p>
                <button
                  data-testid="copy-diagnostics"
                  disabled={diagBusy}
                  onClick={async () => {
                    setDiagBusy(true);
                    try {
                      const bundle = await api.diagnostics();
                      const text = JSON.stringify(bundle, null, 2);
                      await navigator.clipboard.writeText(text);
                      const warnings = bundle.log?.length ?? 0;
                      onToast(
                        `diagnostics copied (${warnings} log ${
                          warnings === 1 ? "entry" : "entries"
                        })`,
                      );
                    } catch (err) {
                      onToast(errorMessage(err));
                    } finally {
                      setDiagBusy(false);
                    }
                  }}
                  className="mt-2 flex shrink-0 items-center gap-1 rounded-lg border border-ink-700 px-2.5 py-1 text-[10.5px] text-ink-300 hover:border-ember-400/40 hover:text-ink-100 disabled:opacity-50"
                >
                  <CopyIcon className="h-3 w-3" />
                  {diagBusy ? "Gathering…" : "Copy for a bug report"}
                </button>
              </div>

              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label !text-[9px]">Bound Loopback Address</p>
                <p className="selectable mt-1 font-mono text-xs text-ink-200">
                  http://{s.host}:{s.port} <span className="text-ink-400">(local-only)</span>
                </p>
              </div>

              {/* #175 Accessible Chart Palettes */}
              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <ChartPalettePicker />
              </div>

              <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                <p className="micro-label mb-2 !text-[9px]">Keyboard Shortcuts</p>
                <div className="grid grid-cols-2 gap-2 text-xs text-ink-300">
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      n
                    </kbd> 
                    Focus Quick Capture
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      i
                    </kbd> 
                    Inbox
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      a
                    </kbd> 
                    Ask Fleeting
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      l
                    </kbd> 
                    Timeline
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      r
                    </kbd> 
                    Reports
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      t
                    </kbd> 
                    Tasks
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      p
                    </kbd> 
                    Processes
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      /
                    </kbd> 
                    Search
                  </div>
                  <div>
                    <kbd className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 font-mono text-[10px]">
                      s
                    </kbd> 
                    Settings
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
  );
}
