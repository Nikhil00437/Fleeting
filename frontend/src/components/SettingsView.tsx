import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { appColor, appMonogram, fmtSecs, prettyAppName } from "../apps";
import { StackBar } from "./charts";
import {
  ActivityIcon,
  BotIcon,
  CheckIcon,
  CopyIcon,
  CpuIcon,
  DatabaseIcon,
  FolderIcon,
  LinkIcon,
  MicIcon,
  RefreshIcon,
  SearchIcon,
  ShieldIcon,
  SlidersIcon,
  SparkIcon,
  TerminalIcon,
  XIcon,
} from "./Icons";
import type { AppRule, HealthStatus, Settings, WhisperProgress } from "../types";

interface Props {
  onToast: (message: string, kind?: "ok" | "err") => void;
  whisperProgress?: WhisperProgress | null;
}

type SettingsTab = "ai" | "activity" | "apps" | "vault" | "system";

function fmtUptime(secs: number): string {
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function SettingsView({ onToast, whisperProgress }: Props) {
  const [tab, setTab] = useState<SettingsTab>("ai");
  const [s, setS] = useState<Settings | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [saving, setSaving] = useState(false);

  // AI testers
  const [llmTest, setLlmTest] = useState<{ ok?: boolean; text: string; models?: string[] } | null>(
    null,
  );
  const [whisperTest, setWhisperTest] = useState<{ ok?: boolean; text: string } | null>(null);
  const [whisperBusy, setWhisperBusy] = useState(false);

  // App rules state
  const [apps, setApps] = useState<AppRule[] | null>(null);
  const [appQuery, setAppQuery] = useState("");
  const [appFilter, setAppFilter] = useState<"all" | "traced" | "muted">("all");
  const [appSort, setAppSort] = useState<"time" | "sessions" | "name">("time");

  // Chip inputs for excluded apps & watch dirs
  const [newExcluded, setNewExcluded] = useState("");
  const [newWatchDir, setNewWatchDir] = useState("");

  const loadAll = useCallback(() => {
    api
      .settings()
      .then(setS)
      .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"));
    api.knownApps().then(setApps).catch(() => {});
    api.health().then(setHealth).catch(() => {});
  }, [onToast]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function save(changes: Partial<Record<string, unknown>>, label = "settings saved") {
    setSaving(true);
    try {
      setS(await api.updateSettings(changes));
      onToast(label);
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setSaving(false);
    }
  }

  async function toggleApp(app: AppRule) {
    const nextTracked = !app.tracked;
    setApps((list) =>
      (list ?? []).map((a) =>
        a.app_class === app.app_class ? { ...a, tracked: nextTracked } : a,
      ),
    );
    try {
      await api.setAppTracked(app.app_class, nextTracked);
      onToast(
        nextTracked
          ? `tracing enabled for ${prettyAppName(app.app_class)}`
          : `tracing muted for ${prettyAppName(app.app_class)}`,
      );
    } catch (e) {
      setApps((list) =>
        (list ?? []).map((a) =>
          a.app_class === app.app_class ? { ...a, tracked: app.tracked } : a,
        ),
      );
      onToast(e instanceof Error ? e.message : String(e), "err");
    }
  }

  async function bulkSetApps(tracked: boolean, targetApps: AppRule[]) {
    setApps((list) => {
      const targetSet = new Set(targetApps.map((t) => t.app_class));
      return (list ?? []).map((a) => (targetSet.has(a.app_class) ? { ...a, tracked } : a));
    });
    try {
      await Promise.all(targetApps.map((a) => api.setAppTracked(a.app_class, tracked)));
      onToast(tracked ? "enabled shown apps" : "muted shown apps");
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
      api.knownApps().then(setApps).catch(() => {});
    }
  }

  const excludedList = useMemo(
    () =>
      (s?.activity_excluded_apps ?? "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    [s?.activity_excluded_apps],
  );

  const watchDirsList = useMemo(
    () =>
      (s?.activity_watch_dirs ?? "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean),
    [s?.activity_watch_dirs],
  );

  const filteredApps = useMemo(() => {
    if (!apps) return [];
    const q = appQuery.trim().toLowerCase();
    return [...apps]
      .filter((a) => {
        if (appFilter === "traced" && !a.tracked) return false;
        if (appFilter === "muted" && a.tracked) return false;
        if (
          q &&
          !a.app_class.toLowerCase().includes(q) &&
          !prettyAppName(a.app_class).toLowerCase().includes(q)
        )
          return false;
        return true;
      })
      .sort((a, b) => {
        if (appSort === "time") return b.seconds - a.seconds;
        if (appSort === "sessions") return b.sessions - a.sessions;
        return prettyAppName(a.app_class).localeCompare(prettyAppName(b.app_class));
      });
  }, [apps, appQuery, appFilter, appSort]);

  if (!s) {
    return (
      <div className="space-y-3 p-5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="shimmer h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  const tracedCount = (apps ?? []).filter((a) => a.tracked).length;
  const mutedCount = (apps ?? []).length - tracedCount;
  const maxAppSecs = Math.max(...(apps ?? []).map((a) => a.seconds), 1);

  const wp: WhisperProgress | null = whisperProgress ?? s.transcribe_progress ?? null;
  const cachedWhisperSet = new Set([
    ...(s.transcribe_cached_models ?? []),
    ...(wp?.status === "ready" && wp.model ? [wp.model] : []),
  ]);
  const isWhisperWorking =
    whisperBusy || wp?.status === "downloading" || wp?.status === "loading";

  const inputCls =
    "w-full rounded-xl border border-ink-700/90 bg-ink-950/90 px-3 py-2 text-xs text-ink-100 outline-none transition-colors focus:border-ember-500/50";
  const labelCls = "mb-1.5 block text-[10px] font-semibold tracking-wider text-ink-400 uppercase";

  const tabs: Array<{
    id: SettingsTab;
    label: string;
    icon: React.ReactNode;
    badge?: string | number;
  }> = [
    {
      id: "ai",
      label: "AI & Speech",
      icon: <BotIcon className="h-3.5 w-3.5" />,
      badge: s.llm_provider === "none" ? "offline" : s.llm_provider,
    },
    {
      id: "activity",
      label: "Activity & Privacy",
      icon: <ShieldIcon className="h-3.5 w-3.5" />,
      badge: s.activity_running ? "live" : "off",
    },
    {
      id: "apps",
      label: "App Rules",
      icon: <SlidersIcon className="h-3.5 w-3.5" />,
      badge: apps ? `${tracedCount}/${apps.length}` : undefined,
    },
    {
      id: "vault",
      label: "Vault & Ingestion",
      icon: <FolderIcon className="h-3.5 w-3.5" />,
      badge: s.vault_sync ? "sync" : "local",
    },
    {
      id: "system",
      label: "Diagnostics",
      icon: <TerminalIcon className="h-3.5 w-3.5" />,
      badge: health?.ok ? "ok" : undefined,
    },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Top Segmented Control Toolbar (Single-rail layout — no double sidebar!) */}
      <div className="app-toolbar flex h-12 shrink-0 items-center gap-3 px-5">
        <div role="tablist" aria-label="Settings sections" className="settings-tabs flex min-w-0 items-center gap-1 rounded-xl border border-ink-800/90 bg-ink-950/85 p-0.5 text-xs">
          {tabs.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                role="tab"
                aria-selected={active}
                tabIndex={active ? 0 : -1}
                className={`flex items-center gap-1.5 rounded-lg px-3 py-1 transition-all ${
                  active
                    ? "bg-ink-800 font-semibold text-ink-100 shadow-xs"
                    : "text-ink-400 hover:text-ink-200"
                }`}
              >
                <span className={active ? "text-ember-400" : "text-ink-400"}>{t.icon}</span>
                <span>{t.label}</span>
                {t.badge !== undefined && (
                  <span
                    className={`rounded-md px-1.5 py-0.2 font-mono text-[9.5px] ${
                      active
                        ? "bg-ember-500/20 text-ember-300"
                        : "bg-ink-900 text-ink-500"
                    }`}
                  >
                    {t.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={async () => {
              await navigator.clipboard.writeText(s.config_path);
              onToast("config.toml path copied");
            }}
            className="hidden items-center gap-1.5 rounded-xl border border-ink-800 bg-ink-950/70 px-2.5 py-1 font-mono text-[10.5px] text-ink-300 transition-colors hover:border-ember-400/40 hover:text-ink-100 xl:flex"
            title="Copy config.toml path"
          >
            <CopyIcon className="h-3 w-3 text-ink-400" />
            <span className="max-w-48 truncate">{s.config_path}</span>
          </button>

          <span className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 font-mono text-[10.5px] font-medium text-emerald-300">
            {saving ? "Saving…" : "Auto-saved · TOML"}
          </span>
        </div>
      </div>

      {/* Scrollable System Control Center */}
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-6xl space-y-4">
          {/* 5-Card Live System Architecture Strip */}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
            <button
              onClick={() => setTab("ai")}
              className={`glass rounded-2xl p-3 text-left transition-all ${
                tab === "ai" ? "ring-1 ring-ember-400/40" : "hover:border-ink-700"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="micro-label !text-[9px]">Local LLM</span>
                <span
                  className={`h-2 w-2 rounded-full ${
                    s.llm_provider !== "none" ? "bg-ember-400" : "bg-ink-500"
                  }`}
                />
              </div>
              <p className="mt-1.5 truncate font-mono text-xs font-bold text-ink-100">
                {s.llm_model || "auto"}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-ink-400">
                {s.llm_provider} · {s.llm_timeout_secs}s timeout
              </p>
            </button>

            <button
              onClick={() => setTab("ai")}
              className={`glass rounded-2xl p-3 text-left transition-all ${
                tab === "ai" ? "ring-1 ring-iris-400/40" : "hover:border-ink-700"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="micro-label !text-[9px]">Whisper STT</span>
                <span
                  className={`h-2 w-2 rounded-full ${
                    s.transcribe_loaded || wp?.status === "ready"
                      ? "bg-emerald-400"
                      : "bg-iris-400"
                  }`}
                />
              </div>
              <p className="mt-1.5 truncate font-mono text-xs font-bold text-ink-100 uppercase">
                {s.transcribe_model} ({s.transcribe_language})
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-iris-300">
                {s.transcribe_loaded
                  ? "Warm in RAM"
                  : cachedWhisperSet.has(s.transcribe_model)
                    ? "Cached on disk"
                    : "On-demand download"}
              </p>
            </button>

            <button
              onClick={() => setTab("activity")}
              className={`glass rounded-2xl p-3 text-left transition-all ${
                tab === "activity" ? "ring-1 ring-emerald-400/40" : "hover:border-ink-700"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="micro-label !text-[9px]">Hyprland Collector</span>
                <span
                  className={`h-2 w-2 rounded-full ${
                    s.activity_running && !s.activity_paused
                      ? "bg-emerald-400 pulse-dot"
                      : "bg-amber-400"
                  }`}
                />
              </div>
              <p className="mt-1.5 truncate font-mono text-xs font-bold text-ink-100">
                {!s.activity_running
                  ? "Stopped"
                  : s.activity_paused
                    ? "Paused"
                    : `${s.activity_poll_secs}s Poll`}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-emerald-300">
                Idle cutoff: {s.activity_idle_after_min}m
              </p>
            </button>

            <button
              onClick={() => setTab("apps")}
              className={`glass rounded-2xl p-3 text-left transition-all ${
                tab === "apps" ? "ring-1 ring-cyan-400/40" : "hover:border-ink-700"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="micro-label !text-[9px]">App Rules</span>
                <SlidersIcon className="h-3 w-3 text-cyan-400" />
              </div>
              <p className="mt-1.5 truncate font-mono text-xs font-bold text-ink-100">
                {tracedCount} Traced
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-ink-400">
                {mutedCount} muted · {excludedList.length} blocked
              </p>
            </button>

            <button
              onClick={() => setTab("vault")}
              className={`glass col-span-2 rounded-2xl p-3 text-left transition-all sm:col-span-1 ${
                tab === "vault" ? "ring-1 ring-ember-400/40" : "hover:border-ink-700"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="micro-label !text-[9px]">Obsidian Vault</span>
                <span
                  className={`h-2 w-2 rounded-full ${
                    s.vault_writable ? "bg-emerald-400" : "bg-red-400"
                  }`}
                />
              </div>
              <p className="mt-1.5 truncate font-mono text-xs font-bold text-ink-100">
                {s.vault_sync ? "Live Mirror" : "Local Only"}
              </p>
              <p className="mt-0.5 truncate font-mono text-[10px] text-ink-400">
                {s.vault_writable ? "Writable · Markdown" : "Check permissions"}
              </p>
            </button>
          </div>

          {/* ==================== COMPARTMENT 1: AI & SPEECH ==================== */}
          {tab === "ai" && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {/* Local LLM Compartment */}
                <section className="glass-studio flex flex-col justify-between rounded-2xl p-5">
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ember-500/15 text-ember-300 ring-1 ring-ember-400/30">
                        <BotIcon className="h-4.5 w-4.5" />
                      </div>
                      <div>
                        <h2 className="text-sm font-semibold text-ink-100">Local LLM Engine</h2>
                        <p className="text-xs text-ink-400">
                          Generates titles, summaries, tags, action items & midnight digests
                        </p>
                      </div>
                    </div>

                    {/* Visual Provider Cards */}
                    <div>
                      <label className={labelCls}>Inference Provider</label>
                      <div className="grid grid-cols-3 gap-2.5">
                        {[
                          { id: "ollama", title: "Ollama", desc: "127.0.0.1:11434" },
                          { id: "lmstudio", title: "LM Studio", desc: "OpenAI API" },
                          { id: "none", title: "Offline Rules", desc: "Deterministic" },
                        ].map((p) => {
                          const active = s.llm_provider === p.id;
                          return (
                            <button
                              key={p.id}
                              onClick={() =>
                                void save({ llm_provider: p.id }, `provider: ${p.title}`)
                              }
                              className={`rounded-xl border p-3 text-left transition-all ${
                                active
                                  ? "border-ember-400/50 bg-ember-500/15 text-ink-100 shadow-xs"
                                  : "border-ink-800 bg-ink-950/65 text-ink-300 hover:border-ink-700"
                              }`}
                            >
                              <p className="text-xs font-semibold">{p.title}</p>
                              <p className="mt-0.5 font-mono text-[10px] text-ink-400">{p.desc}</p>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div>
                        <label className={labelCls}>Model Identifier</label>
                        <input
                          value={s.llm_model}
                          onChange={(e) => setS({ ...s, llm_model: e.target.value })}
                          onBlur={() => void save({ llm_model: s.llm_model }, "LLM model updated")}
                          className={`${inputCls} font-mono`}
                          placeholder="auto (first available)"
                          spellCheck={false}
                        />
                      </div>
                      <div>
                        <label className={labelCls}>Timeout (seconds)</label>
                        <input
                          type="number"
                          value={s.llm_timeout_secs}
                          onChange={(e) => setS({ ...s, llm_timeout_secs: Number(e.target.value) })}
                          onBlur={() =>
                            void save({ llm_timeout_secs: s.llm_timeout_secs }, "timeout updated")
                          }
                          className={`${inputCls} font-mono`}
                        />
                      </div>
                    </div>

                    <div>
                      <label className={labelCls}>Endpoint Base URL</label>
                      <input
                        value={s.llm_base_url}
                        onChange={(e) => setS({ ...s, llm_base_url: e.target.value })}
                        onBlur={() =>
                          void save({ llm_base_url: s.llm_base_url }, "endpoint URL updated")
                        }
                        className={`${inputCls} font-mono`}
                        spellCheck={false}
                      />
                    </div>
                  </div>

                  {/* Connection Tester + Clickable Discovered Models */}
                  <div className="mt-5 border-t border-ink-800/80 pt-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        onClick={async () => {
                          setLlmTest({ text: "probing local endpoint…" });
                          try {
                            const r = await api.testLLM();
                            setLlmTest({
                              ok: r.ok,
                              text: r.ok
                                ? `Connected (${(r.models ?? []).length} models available)`
                                : r.detail ?? "Unreachable",
                              models: r.models,
                            });
                          } catch (e) {
                            setLlmTest({
                              ok: false,
                              text: e instanceof Error ? e.message : String(e),
                            });
                          }
                        }}
                        className="flex items-center gap-1.5 rounded-xl border border-ember-500/40 bg-ember-500/15 px-3.5 py-2 text-xs font-semibold text-ember-200 transition-colors hover:bg-ember-500/25"
                      >
                        <CpuIcon className="h-3.5 w-3.5" /> Test Connection & Discover Models
                      </button>
                      {llmTest && (
                        <span
                          className={`text-xs font-medium ${
                            llmTest.ok === true
                              ? "text-emerald-300"
                              : llmTest.ok === false
                                ? "text-red-300"
                                : "text-ink-300"
                          }`}
                        >
                          {llmTest.text}
                        </span>
                      )}
                    </div>

                    {llmTest?.models && llmTest.models.length > 0 && (
                      <div className="mt-3">
                        <p className="micro-label mb-1.5 !text-[9px]">
                          Click a discovered model to activate:
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {llmTest.models.map((m) => (
                            <button
                              key={m}
                              onClick={() => {
                                setS({ ...s, llm_model: m });
                                void save({ llm_model: m }, `selected model: ${m}`);
                              }}
                              className={`rounded-lg border px-2.5 py-1 font-mono text-[11px] transition-colors ${
                                s.llm_model === m
                                  ? "border-ember-400 bg-ember-500/25 text-ember-200"
                                  : "border-ink-700 bg-ink-950 text-ink-300 hover:border-ember-400/40 hover:text-ink-100"
                              }`}
                            >
                              {m}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </section>

                {/* Whisper Speech-to-Text Compartment */}
                <section className="glass-studio flex flex-col justify-between rounded-2xl p-5">
                  <div className="space-y-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-iris-500/15 text-iris-300 ring-1 ring-iris-400/30">
                        <MicIcon className="h-4.5 w-4.5" />
                      </div>
                      <div>
                        <h2 className="text-sm font-semibold text-ink-100">
                          Whisper Speech-to-Text (faster-whisper)
                        </h2>
                        <p className="text-xs text-ink-400">
                          100% offline CPU int8 voice memo & YouTube audio transcription
                        </p>
                      </div>
                    </div>

                    {/* 4-tier Visual Model Selector */}
                    <div>
                      <label className={labelCls}>Whisper Model Size</label>
                      <div className="grid grid-cols-2 gap-2.5">
                        {[
                          { id: "tiny", name: "tiny", size: "~39 MB", desc: "Fastest · quick memos" },
                          {
                            id: "base",
                            name: "base",
                            size: "~75 MB",
                            desc: "Balanced · recommended",
                          },
                          {
                            id: "small",
                            name: "small",
                            size: "~244 MB",
                            desc: "High accuracy · multilingual",
                          },
                          {
                            id: "medium",
                            name: "medium",
                            size: "~769 MB",
                            desc: "Studio grade · slowest",
                          },
                        ].map((tier) => {
                          const active = s.transcribe_model === tier.id;
                          const isWarm =
                            (s.transcribe_loaded && active) ||
                            (wp?.status === "ready" && wp.model === tier.id);
                          const isCached = cachedWhisperSet.has(tier.id);
                          const isTierDownloading =
                            (wp?.status === "downloading" || wp?.status === "loading") &&
                            wp.model === tier.id;

                          return (
                            <button
                              key={tier.id}
                              disabled={isWhisperWorking}
                              onClick={() => {
                                setWhisperTest(null);
                                void save(
                                  { transcribe_model: tier.id },
                                  `whisper set to '${tier.id}'`,
                                );
                              }}
                              className={`relative overflow-hidden rounded-xl border p-3 text-left transition-all ${
                                active
                                  ? "border-iris-400/50 bg-iris-500/15 text-ink-100 shadow-xs"
                                  : "border-ink-800 bg-ink-950/65 text-ink-300 hover:border-ink-700"
                              } ${isWhisperWorking ? "cursor-wait opacity-80" : ""}`}
                            >
                              <div className="flex items-center justify-between gap-1.5">
                                <span className="font-mono text-xs font-bold uppercase">
                                  {tier.name}
                                </span>
                                <div className="flex items-center gap-1.5">
                                  {isWarm ? (
                                    <span className="rounded-md border border-emerald-500/30 bg-emerald-500/15 px-1.5 py-0.2 font-mono text-[9.5px] font-semibold text-emerald-300">
                                      in RAM
                                    </span>
                                  ) : isCached ? (
                                    <span className="rounded-md border border-ink-700 bg-ink-850 px-1.5 py-0.2 font-mono text-[9.5px] text-emerald-300/90">
                                      cached
                                    </span>
                                  ) : (
                                    <span className="rounded-md border border-iris-400/25 bg-iris-500/10 px-1.5 py-0.2 font-mono text-[9.5px] text-iris-300/80">
                                      download
                                    </span>
                                  )}
                                  <span className="font-mono text-[10px] text-iris-300">
                                    {tier.size}
                                  </span>
                                </div>
                              </div>
                              <p className="mt-1 text-[11px] text-ink-400">{tier.desc}</p>
                              {isTierDownloading && (
                                <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-ink-900">
                                  <div
                                    className="h-full bg-gradient-to-r from-iris-400 to-ember-400 transition-all duration-150"
                                    style={{ width: `${Math.max(5, wp.percent)}%` }}
                                  />
                                </div>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <label className={labelCls}>Transcription Language</label>
                      <div className="flex gap-1.5">
                        <input
                          value={s.transcribe_language}
                          onChange={(e) => setS({ ...s, transcribe_language: e.target.value })}
                          onBlur={() =>
                            void save(
                              { transcribe_language: s.transcribe_language },
                              "language updated",
                            )
                          }
                          className={`${inputCls} font-mono`}
                          placeholder="auto"
                        />
                        {["auto", "en", "hi"].map((lang) => (
                          <button
                            key={lang}
                            onClick={() => {
                              setS({ ...s, transcribe_language: lang });
                              void save({ transcribe_language: lang }, `language: ${lang}`);
                            }}
                            className={`shrink-0 rounded-xl border px-3 font-mono text-xs transition-colors ${
                              s.transcribe_language === lang
                                ? "border-iris-400/50 bg-iris-500/20 text-iris-200"
                                : "border-ink-700 bg-ink-900 text-ink-400 hover:text-ink-200"
                            }`}
                          >
                            {lang}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 space-y-3 border-t border-ink-800/80 pt-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        disabled={isWhisperWorking}
                        onClick={async () => {
                          setWhisperBusy(true);
                          const needsDownload = !cachedWhisperSet.has(s.transcribe_model);
                          setWhisperTest({
                            text: needsDownload
                              ? `downloading '${s.transcribe_model}' from Hugging Face…`
                              : `loading '${s.transcribe_model}' into CPU int8 memory…`,
                          });
                          try {
                            const r = await api.testWhisper();
                            setWhisperTest({
                              ok: true,
                              text: `✓ '${r.model}' model verified & warm in RAM`,
                            });
                            loadAll();
                          } catch (e) {
                            setWhisperTest({
                              ok: false,
                              text: e instanceof Error ? e.message : String(e),
                            });
                          } finally {
                            setWhisperBusy(false);
                          }
                        }}
                        className={`flex items-center gap-1.5 rounded-xl border px-3.5 py-2 text-xs font-semibold transition-colors ${
                          isWhisperWorking
                            ? "cursor-wait border-iris-400/30 bg-iris-500/10 text-iris-300"
                            : "border-iris-400/40 bg-iris-500/15 text-iris-200 hover:bg-iris-500/25"
                        }`}
                      >
                        <MicIcon className="h-3.5 w-3.5" />
                        {wp?.status === "downloading"
                          ? `Downloading '${wp.model}' (${wp.percent}%)…`
                          : wp?.status === "loading" || whisperBusy
                            ? `Loading '${s.transcribe_model}' into RAM…`
                            : !cachedWhisperSet.has(s.transcribe_model)
                              ? `Download & Warm Up '${s.transcribe_model}'`
                              : "Warm Up & Verify Whisper"}
                      </button>

                      {!isWhisperWorking && whisperTest && (
                        <span
                          className={`text-xs font-medium ${
                            whisperTest.ok === true
                              ? "text-emerald-300"
                              : whisperTest.ok === false
                                ? "text-red-300"
                                : "text-ink-300"
                          }`}
                        >
                          {whisperTest.text}
                        </span>
                      )}
                    </div>

                    {/* Live Download & Warm-Up Progress Bar */}
                    {(isWhisperWorking ||
                      wp?.status === "downloading" ||
                      wp?.status === "loading" ||
                      (wp?.status === "ready" && wp.model === s.transcribe_model)) && (
                      <div className="rounded-xl border border-ink-800 bg-ink-950/80 p-3">
                        <div className="mb-1.5 flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span
                              className={`h-2 w-2 rounded-full ${
                                wp?.status === "downloading"
                                  ? "animate-ping bg-iris-400"
                                  : wp?.status === "loading" || whisperBusy
                                    ? "animate-pulse bg-ember-400"
                                    : "bg-emerald-400"
                              }`}
                            />
                            <span className="font-mono text-[10.5px] font-semibold tracking-wider text-ink-200 uppercase">
                              {wp?.status === "downloading"
                                ? `Downloading '${wp.model}' weights`
                                : wp?.status === "loading" || whisperBusy
                                  ? `Warming '${s.transcribe_model}' in CPU int8 RAM`
                                  : `Model '${wp?.model ?? s.transcribe_model}' ready`}
                            </span>
                          </div>

                          <div className="flex items-center gap-2 font-mono text-[11px]">
                            {wp && wp.total_bytes > 0 && wp.status === "downloading" && (
                              <span className="text-ink-400">
                                {fmtMB(wp.downloaded_bytes)} / {fmtMB(wp.total_bytes)}
                              </span>
                            )}
                            {wp && wp.speed_bps > 0 && wp.status === "downloading" && (
                              <span className="text-iris-300">
                                {(wp.speed_bps / (1024 * 1024)).toFixed(1)} MB/s
                              </span>
                            )}
                            <span
                              className={`font-bold ${
                                wp?.status === "ready" ? "text-emerald-300" : "text-ink-100"
                              }`}
                            >
                              {wp?.percent ?? (whisperBusy ? 10 : 100)}%
                            </span>
                          </div>
                        </div>

                        <div className="h-2 w-full overflow-hidden rounded-full bg-ink-900 ring-1 ring-ink-800">
                          <div
                            className={`h-full rounded-full transition-all duration-200 ${
                              wp?.status === "ready"
                                ? "bg-emerald-400"
                                : "bg-gradient-to-r from-iris-500 via-ember-400 to-emerald-400"
                            }`}
                            style={{
                              width: `${Math.max(
                                4,
                                wp?.percent ?? (whisperBusy ? 15 : 100),
                              )}%`,
                            }}
                          />
                        </div>

                        <p className="mt-1.5 truncate font-mono text-[10.5px] text-ink-400">
                          {wp?.detail ||
                            whisperTest?.text ||
                            `Preparing faster-whisper '${s.transcribe_model}'…`}
                        </p>
                      </div>
                    )}
                  </div>
                </section>
              </div>

              {/* Local Enrichment Pipeline Architecture Overview */}
              <div className="glass-studio rounded-2xl p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="micro-label flex items-center gap-1.5">
                    <SparkIcon className="h-3 w-3 text-ember-400" />
                    Zero-Cloud Enrichment Pipeline
                  </span>
                  <span className="font-mono text-[10.5px] text-ink-400">
                    100% On-Device Processing
                  </span>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                    <p className="text-xs font-semibold text-ink-100">1. Capture & Ingest</p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                      Text notes, microphone voice memos, and YouTube URLs are saved immediately to
                      SQLite WAL and queued for background enrichment.
                    </p>
                  </div>
                  <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                    <p className="text-xs font-semibold text-ink-100">
                      2. Transcribe & Synthesize
                    </p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                      Audio & captionless videos run through CTranslate2{" "}
                      <code className="font-mono text-iris-300">faster-whisper</code>, then your
                      local LLM extracts titles, tags, and action items.
                    </p>
                  </div>
                  <div className="rounded-xl border border-ink-800/80 bg-ink-950/60 p-3">
                    <p className="text-xs font-semibold text-ink-100">3. Index & Vault Mirror</p>
                    <p className="mt-1 text-[11.5px] leading-relaxed text-ink-300">
                      Enriched notes are indexed in SQLite FTS5 (BM25 ranking) and mirrored as clean
                      Markdown files into your Obsidian vault.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ==================== COMPARTMENT 2: ACTIVITY & PRIVACY ==================== */}
          {tab === "activity" && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <section className="glass-studio space-y-4 rounded-2xl p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30">
                    <ActivityIcon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-ink-100">
                      Hyprland Window Collector & Schedule
                    </h2>
                    <p className="text-xs text-ink-400">
                      Tracks active windows with cursor-idle detection and midnight digests
                    </p>
                  </div>
                </div>

                <div className="space-y-3 rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                  <label className="flex cursor-pointer items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-ink-100">
                        Enable Window Activity Collector
                      </p>
                      <p className="text-[11px] text-ink-400">
                        {s.activity_running
                          ? "Collector is actively polling Hyprland"
                          : "Requires server restart when toggled"}
                      </p>
                    </div>
                    <Toggle
                      checked={s.activity_enabled}
                      onChange={(v) =>
                        void save(
                          { activity_enabled: v },
                          v ? "collector enabled (restart to apply)" : "collector disabled",
                        )
                      }
                    />
                  </label>

                  <div className="border-t border-ink-800/80 pt-3">
                    <label className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-ink-100">
                          Automated Midnight Daily Report
                        </p>
                        <p className="text-[11px] text-ink-400">
                          Compacts the past 24h into a readable digest at 12:00 AM
                        </p>
                      </div>
                      <Toggle
                        checked={s.activity_auto_daily_log}
                        onChange={(v) =>
                          void save(
                            { activity_auto_daily_log: v },
                            v ? "midnight report enabled" : "midnight report disabled",
                          )
                        }
                      />
                    </label>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="rounded-xl border border-ink-800 bg-ink-950/50 p-3.5">
                    <label className={labelCls}>Poll Interval (seconds)</label>
                    <input
                      type="number"
                      min={5}
                      max={300}
                      value={s.activity_poll_secs}
                      onChange={(e) => setS({ ...s, activity_poll_secs: Number(e.target.value) })}
                      onBlur={() =>
                        void save(
                          { activity_poll_secs: s.activity_poll_secs },
                          "poll interval updated",
                        )
                      }
                      className={`${inputCls} font-mono`}
                    />
                    <div className="mt-2 flex gap-1.5">
                      {[10, 20, 30, 60].map((sec) => (
                        <button
                          key={sec}
                          onClick={() => {
                            setS({ ...s, activity_poll_secs: sec });
                            void save({ activity_poll_secs: sec }, `poll set to ${sec}s`);
                          }}
                          className={`rounded-lg px-2.5 py-0.5 font-mono text-[10px] ${
                            s.activity_poll_secs === sec
                              ? "bg-ember-500/25 font-semibold text-ember-300"
                              : "bg-ink-850 text-ink-400 hover:text-ink-200"
                          }`}
                        >
                          {sec}s
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-xl border border-ink-800 bg-ink-950/50 p-3.5">
                    <label className={labelCls}>Idle Cutoff (minutes cursor still)</label>
                    <input
                      type="number"
                      min={1}
                      max={60}
                      value={s.activity_idle_after_min}
                      onChange={(e) =>
                        setS({ ...s, activity_idle_after_min: Number(e.target.value) })
                      }
                      onBlur={() =>
                        void save(
                          { activity_idle_after_min: s.activity_idle_after_min },
                          "idle threshold updated",
                        )
                      }
                      className={`${inputCls} font-mono`}
                    />
                    <div className="mt-2 flex gap-1.5">
                      {[2, 3, 5, 10].map((min) => (
                        <button
                          key={min}
                          onClick={() => {
                            setS({ ...s, activity_idle_after_min: min });
                            void save({ activity_idle_after_min: min }, `idle cutoff set to ${min}m`);
                          }}
                          className={`rounded-lg px-2.5 py-0.5 font-mono text-[10px] ${
                            s.activity_idle_after_min === min
                              ? "bg-ember-500/25 font-semibold text-ember-300"
                              : "bg-ink-850 text-ink-400 hover:text-ink-200"
                          }`}
                        >
                          {min}m
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </section>

              <section className="glass-studio space-y-4 rounded-2xl p-5">
                <div>
                  <label className={labelCls}>
                    Hard Blocklist (never traced, overrides per-app rules)
                  </label>
                  <div className="mb-2.5 flex flex-wrap gap-1.5">
                    {excludedList.map((item) => (
                      <span
                        key={item}
                        className="flex items-center gap-1.5 rounded-lg border border-red-400/30 bg-red-500/10 px-2.5 py-1 font-mono text-xs text-red-200"
                      >
                        {item}
                        <button
                          onClick={() => {
                            const next = excludedList.filter((x) => x !== item).join(", ");
                            setS({ ...s, activity_excluded_apps: next });
                            void save(
                              { activity_excluded_apps: next },
                              `removed '${item}' from blocklist`,
                            );
                          }}
                          className="text-red-300/70 hover:text-red-100"
                        >
                          <XIcon className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    {excludedList.length === 0 && (
                      <span className="text-xs text-ink-500">No blocklisted app fragments.</span>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <input
                      value={newExcluded}
                      onChange={(e) => setNewExcluded(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && newExcluded.trim()) {
                          const next = [...excludedList, newExcluded.trim()].join(", ");
                          setS({ ...s, activity_excluded_apps: next });
                          setNewExcluded("");
                          void save({ activity_excluded_apps: next }, "blocklist updated");
                        }
                      }}
                      placeholder="Add app fragment (e.g. keepassxc, 1Password)…"
                      className={`${inputCls} font-mono`}
                    />
                    <button
                      onClick={() => {
                        if (!newExcluded.trim()) return;
                        const next = [...excludedList, newExcluded.trim()].join(", ");
                        setS({ ...s, activity_excluded_apps: next });
                        setNewExcluded("");
                        void save({ activity_excluded_apps: next }, "blocklist updated");
                      }}
                      className="shrink-0 rounded-xl border border-ink-700 bg-ink-850 px-3.5 text-xs font-medium text-ink-200 hover:border-ember-400/40"
                    >
                      + Add
                    </button>
                  </div>
                </div>

                <div className="border-t border-ink-800/80 pt-4">
                  <label className={labelCls}>
                    Watched Workspace Directories (file & git metadata for daily reports)
                  </label>
                  <div className="mb-2.5 flex flex-wrap gap-1.5">
                    {watchDirsList.map((dir) => (
                      <span
                        key={dir}
                        className="flex items-center gap-1.5 rounded-lg border border-cyan-400/30 bg-cyan-500/10 px-2.5 py-1 font-mono text-xs text-cyan-200"
                      >
                        <FolderIcon className="h-3 w-3 text-cyan-400" />
                        {dir}
                        <button
                          onClick={() => {
                            const next = watchDirsList.filter((x) => x !== dir).join(", ");
                            setS({ ...s, activity_watch_dirs: next });
                            void save({ activity_watch_dirs: next }, "watch dirs updated");
                          }}
                          className="text-cyan-300/70 hover:text-cyan-100"
                        >
                          <XIcon className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    <input
                      value={newWatchDir}
                      onChange={(e) => setNewWatchDir(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && newWatchDir.trim()) {
                          const next = [...watchDirsList, newWatchDir.trim()].join(", ");
                          setS({ ...s, activity_watch_dirs: next });
                          setNewWatchDir("");
                          void save({ activity_watch_dirs: next }, "watch dirs updated");
                        }
                      }}
                      placeholder="Add directory (e.g. ~/Projects, ~/Notes)…"
                      className={`${inputCls} font-mono`}
                    />
                    <button
                      onClick={() => {
                        if (!newWatchDir.trim()) return;
                        const next = [...watchDirsList, newWatchDir.trim()].join(", ");
                        setS({ ...s, activity_watch_dirs: next });
                        setNewWatchDir("");
                        void save({ activity_watch_dirs: next }, "watch dirs updated");
                      }}
                      className="shrink-0 rounded-xl border border-ink-700 bg-ink-850 px-3.5 text-xs font-medium text-ink-200 hover:border-cyan-400/40"
                    >
                      + Add
                    </button>
                  </div>
                  <p className="mt-2 text-[11px] text-ink-400">
                    Scans modified filenames and git commit subjects only — file contents are never
                    read.
                  </p>
                </div>
              </section>
            </div>
          )}

          {/* ==================== COMPARTMENT 3: APP RULES ==================== */}
          {tab === "apps" && (
            <div className="space-y-4">
              <div className="glass-studio rounded-2xl p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <h2 className="text-sm font-semibold text-ink-100">
                      Per-Application Tracing Rules
                    </h2>
                    <p className="text-xs text-ink-400">
                      Every application seen by Hyprland appears here. Toggle tracing per app at any
                      time.
                    </p>
                  </div>
                  <div className="flex items-center gap-4 font-mono text-xs">
                    <span className="text-ink-400">
                      Traced: <strong className="text-emerald-300">{tracedCount}</strong>
                    </span>
                    <span className="text-ink-700">|</span>
                    <span className="text-ink-400">
                      Muted: <strong className="text-ember-300">{mutedCount}</strong>
                    </span>
                  </div>
                </div>

                <StackBar
                  segments={[
                    {
                      key: "traced",
                      value: tracedCount,
                      color: "#4b786b",
                      title: `Traced: ${tracedCount}`,
                    },
                    {
                      key: "muted",
                      value: mutedCount,
                      color: "#a34e49",
                      title: `Muted: ${mutedCount}`,
                    },
                  ]}
                  selectedKey={appFilter === "all" ? null : appFilter}
                  onSelect={(k) =>
                    setAppFilter((cur) => (cur === k ? "all" : (k as "traced" | "muted")))
                  }
                />

                <div className="mt-3.5 flex flex-wrap items-center gap-2">
                  <div className="flex rounded-xl border border-ink-800 bg-ink-950 p-0.5 text-xs">
                    {[
                      { id: "all" as const, label: "All", count: (apps ?? []).length },
                      { id: "traced" as const, label: "Traced", count: tracedCount },
                      { id: "muted" as const, label: "Muted", count: mutedCount },
                    ].map((f) => (
                      <button
                        key={f.id}
                        onClick={() => setAppFilter(f.id)}
                        className={`rounded-lg px-2.5 py-1 transition-all ${
                          appFilter === f.id
                            ? "bg-ink-800 font-semibold text-ink-100"
                            : "text-ink-400 hover:text-ink-200"
                        }`}
                      >
                        {f.label}{" "}
                        <span className="ml-1 font-mono text-[10px] opacity-75">{f.count}</span>
                      </button>
                    ))}
                  </div>

                  <div className="flex rounded-xl border border-ink-800 bg-ink-950 p-0.5 text-xs">
                    {[
                      { id: "time" as const, label: "Most Time" },
                      { id: "sessions" as const, label: "Sessions" },
                      { id: "name" as const, label: "A–Z" },
                    ].map((st) => (
                      <button
                        key={st.id}
                        onClick={() => setAppSort(st.id)}
                        className={`rounded-lg px-2.5 py-1 transition-all ${
                          appSort === st.id
                            ? "bg-iris-500/20 font-medium text-iris-300"
                            : "text-ink-400 hover:text-ink-200"
                        }`}
                      >
                        {st.label}
                      </button>
                    ))}
                  </div>

                  {filteredApps.length > 0 && (
                    <div className="flex items-center gap-1.5 text-xs">
                      <button
                        onClick={() => void bulkSetApps(true, filteredApps)}
                        className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/20"
                      >
                        Trace Shown
                      </button>
                      <button
                        onClick={() => void bulkSetApps(false, filteredApps)}
                        className="rounded-xl border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] text-ink-300 hover:border-red-400/40 hover:text-red-300"
                      >
                        Mute Shown
                      </button>
                    </div>
                  )}

                  <div className="relative ml-auto w-56">
                    <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 h-3 w-3 -translate-y-1/2 text-ink-400" />
                    <input
                      value={appQuery}
                      onChange={(e) => setAppQuery(e.target.value)}
                      placeholder="Search application…"
                      className="h-8 w-full rounded-xl border border-ink-800 bg-ink-950/90 pr-7 pl-7 text-xs text-ink-100 placeholder-ink-500 outline-none focus:border-ember-500/50"
                    />
                    {appQuery && (
                      <button
                        onClick={() => setAppQuery("")}
                        className="absolute top-1/2 right-2 -translate-y-1/2 text-ink-400 hover:text-ink-200"
                      >
                        <XIcon className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {apps === null ? (
                <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} className="shimmer h-16 rounded-2xl" />
                  ))}
                </div>
              ) : filteredApps.length === 0 ? (
                <div className="glass rounded-2xl py-12 text-center text-xs text-ink-400">
                  No matching applications found.
                </div>
              ) : (
                <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
                  {filteredApps.map((app) => {
                    const color = appColor(app.app_class);
                    const pct = Math.max(4, Math.round((app.seconds / maxAppSecs) * 100));
                    return (
                      <div
                        key={app.app_class}
                        className={`glass flex items-center gap-3.5 rounded-2xl px-4 py-3 transition-all ${
                          app.tracked ? "" : "opacity-60"
                        }`}
                      >
                        <span
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl font-mono text-[10.5px] font-bold"
                          style={{
                            background: app.tracked ? `${color}22` : "rgba(67,81,117,0.2)",
                            color: app.tracked ? color : "#8b98b8",
                            border: `1px solid ${app.tracked ? `${color}4d` : "rgba(67,81,117,0.35)"}`,
                          }}
                        >
                          {appMonogram(app.app_class)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-xs font-semibold text-ink-100">
                              {prettyAppName(app.app_class)}
                            </span>
                            <span className="truncate font-mono text-[10px] text-ink-500">
                              {app.app_class}
                            </span>
                            <span className="ml-auto shrink-0 font-mono text-xs font-semibold text-ink-200">
                              {app.seconds > 0 ? fmtSecs(app.seconds) : "0s"}
                            </span>
                          </div>
                          <div className="mt-1.5 flex items-center gap-2.5">
                            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-900">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${app.seconds > 0 ? pct : 0}%`,
                                  background: app.tracked ? color : "#435175",
                                }}
                              />
                            </div>
                            <span className="shrink-0 font-mono text-[10px] text-ink-400">
                              {app.sessions} sess {app.last_day ? `· ${app.last_day}` : ""}
                            </span>
                          </div>
                        </div>
                        <Toggle checked={app.tracked} onChange={() => void toggleApp(app)} />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* ==================== COMPARTMENT 4: VAULT & INGESTION ==================== */}
          {tab === "vault" && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <section className="glass-studio space-y-4 rounded-2xl p-5">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ember-500/15 text-ember-300 ring-1 ring-ember-400/30">
                    <FolderIcon className="h-4.5 w-4.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-semibold text-ink-100">Obsidian Markdown Vault</h2>
                    <p className="text-xs text-ink-400">
                      Mirror enriched notes & daily reports as plain Markdown files
                    </p>
                  </div>
                  <span
                    className={`ml-auto rounded-full px-2.5 py-0.5 font-mono text-[10px] ${
                      s.vault_writable
                        ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30"
                        : "bg-red-500/15 text-red-300 ring-1 ring-red-400/30"
                    }`}
                  >
                    {s.vault_writable ? "✓ writable" : "✗ not writable"}
                  </span>
                </div>

                <div>
                  <label className={labelCls}>Vault Directory Path</label>
                  <div className="flex gap-2">
                    <input
                      value={s.vault_dir}
                      onChange={(e) => setS({ ...s, vault_dir: e.target.value })}
                      className={`${inputCls} font-mono`}
                      spellCheck={false}
                    />
                    <button
                      onClick={() =>
                        void save({ vault_dir: s.vault_dir }, "vault directory updated")
                      }
                      disabled={saving}
                      className="shrink-0 rounded-xl bg-gradient-to-br from-ember-400 to-ember-600 px-4 text-xs font-semibold text-ink-950 shadow-sm hover:brightness-110 disabled:opacity-50"
                    >
                      Save Path
                    </button>
                  </div>
                </div>

                <div className="space-y-3 rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                  <label className="flex cursor-pointer items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-ink-100">Auto-Sync Notes to Vault</p>
                      <p className="text-[11px] text-ink-400">
                        Writes clean frontmatter + markdown when capture enrichment finishes
                      </p>
                    </div>
                    <Toggle
                      checked={s.vault_sync}
                      onChange={(v) =>
                        void save({ vault_sync: v }, v ? "vault sync enabled" : "vault sync paused")
                      }
                    />
                  </label>

                  <div className="border-t border-ink-800/80 pt-3">
                    <label className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-ink-100">
                          Mirror Daily Reports to Vault
                        </p>
                        <p className="text-[11px] text-ink-400">
                          Also saves midnight activity digests under <code>Daily/YYYY-MM-DD.md</code>
                        </p>
                      </div>
                      <Toggle
                        checked={s.activity_mirror_daily_log}
                        onChange={(v) =>
                          void save(
                            { activity_mirror_daily_log: v },
                            v
                              ? "daily reports mirror to vault"
                              : "daily reports stay in-app only",
                          )
                        }
                      />
                    </label>
                  </div>
                </div>
              </section>

              <section className="glass-studio space-y-4 rounded-2xl p-5">
                <div>
                  <div className="mb-3 flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-400/30">
                      <LinkIcon className="h-4.5 w-4.5" />
                    </div>
                    <div>
                      <h2 className="text-sm font-semibold text-ink-100">
                        YouTube Ingestion Pipeline
                      </h2>
                      <p className="text-xs text-ink-400">
                        Extracts subtitles via yt-dlp with optional local Whisper fallback
                      </p>
                    </div>
                  </div>

                  <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                    <label className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-ink-100">
                          Whisper Audio Fallback for Captionless Videos
                        </p>
                        <p className="text-[11px] text-ink-400">
                          Downloads audio track and transcribes locally when captions are missing
                        </p>
                      </div>
                      <Toggle
                        checked={s.yt_transcribe_fallback}
                        onChange={(v) =>
                          void save(
                            { yt_transcribe_fallback: v },
                            v
                              ? "YouTube audio fallback enabled"
                              : "YouTube audio fallback disabled",
                          )
                        }
                      />
                    </label>
                  </div>

                  <div className="mt-3 rounded-xl border border-ink-800 bg-ink-950/50 p-3.5">
                    <label className={labelCls}>Max Audio Fallback Duration (minutes)</label>
                    <div className="flex items-center gap-2.5">
                      <input
                        type="number"
                        min={5}
                        max={240}
                        value={s.yt_max_duration_min}
                        onChange={(e) =>
                          setS({ ...s, yt_max_duration_min: Number(e.target.value) })
                        }
                        onBlur={() =>
                          void save(
                            { yt_max_duration_min: s.yt_max_duration_min },
                            "max duration updated",
                          )
                        }
                        className={`${inputCls} max-w-24 font-mono`}
                      />
                      <div className="flex flex-wrap gap-1.5">
                        {[15, 30, 45, 60, 90, 120].map((m) => (
                          <button
                            key={m}
                            onClick={() => {
                              setS({ ...s, yt_max_duration_min: m });
                              void save({ yt_max_duration_min: m }, `YouTube limit set to ${m}m`);
                            }}
                            className={`rounded-lg px-2.5 py-0.5 font-mono text-[10px] ${
                              s.yt_max_duration_min === m
                                ? "bg-cyan-500/25 font-semibold text-cyan-200"
                                : "bg-ink-850 text-ink-400 hover:text-ink-200"
                            }`}
                          >
                            {m}m
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="border-t border-ink-800/80 pt-4">
                  <label className={labelCls}>System Notifications</label>
                  <div className="rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
                    <label className="flex cursor-pointer items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-ink-100">Desktop Notifications</p>
                        <p className="text-[11px] text-ink-400">
                          Send a native desktop toast when background capture enrichment completes
                        </p>
                      </div>
                      <Toggle
                        checked={s.desktop_notifications}
                        onChange={(v) =>
                          void save(
                            { desktop_notifications: v },
                            v
                              ? "desktop notifications enabled"
                              : "desktop notifications muted",
                          )
                        }
                      />
                    </label>
                  </div>
                </div>
              </section>
            </div>
          )}

          {/* ==================== COMPARTMENT 5: SYSTEM DIAGNOSTICS ==================== */}
          {tab === "system" && (
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
                    <p className="mt-1 flex items-center gap-1 font-mono text-xs font-bold text-emerald-300">
                      <CheckIcon className="h-3.5 w-3.5" /> {health?.ok ? "Healthy" : "Degraded"}
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
          )}
        </div>
      </div>
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
        checked ? "bg-ember-500 shadow-[0_0_10px_rgb(245_158_11/0.35)]" : "bg-ink-700"
      }`}
    >
      <span
        className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-150"
        style={{ transform: checked ? "translateX(16px)" : "translateX(0)" }}
      />
    </button>
  );
}
