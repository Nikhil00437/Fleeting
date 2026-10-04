import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { applySettingsChange, errorMessage, reconcileSettings } from "./settingsState";
import ActivityTab from "./settings/ActivityTab";
import AiTab from "./settings/AiTab";
import AppsTab from "./settings/AppsTab";
import SystemTab from "./settings/SystemTab";
import VaultTab from "./settings/VaultTab";
import { prettyAppName } from "../apps";
import { BotIcon, CopyIcon, FolderIcon, ShieldIcon, SlidersIcon, TerminalIcon } from "./Icons";
import type { AppRule, HealthStatus, Settings, WhisperProgress, VaultSyncResult } from "../types";

export interface Props {
  onToast: (message: string, kind?: "ok" | "err") => void;
  whisperProgress?: WhisperProgress | null;
  initialSettings?: Settings | null;
  defaultTab?: SettingsTab;
  initialResyncResult?: string | null;
}

type SettingsTab = "ai" | "activity" | "apps" | "vault" | "system";



export async function forceVaultResyncAction(
  setResyncing: (val: boolean) => void,
  setResyncResult: (msg: string | null) => void,
  onToast: (message: string, kind?: "ok" | "err") => void,
): Promise<VaultSyncResult | null> {
  setResyncing(true);
  try {
    const res = await api.resyncVault();
    const msg = `Re-synced ${res.synced_notes} notes, imported ${res.imported_notes} notes, updated ${res.tasks_updated} tasks.`;
    setResyncResult(msg);
    onToast(msg, "ok");
    return res;
  } catch (e) {
    const errMsg = e instanceof Error ? e.message : String(e);
    onToast(errMsg, "err");
    return null;
  } finally {
    setResyncing(false);
  }
}

export default function SettingsView({
  onToast,
  whisperProgress,
  initialSettings,
  defaultTab = "ai",
  initialResyncResult = null,
}: Props) {
  const [tab, setTab] = useState<SettingsTab>(defaultTab);
  const [s, setS] = useState<Settings | null>(initialSettings ?? null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [resyncing, setResyncing] = useState(false);
  const [resyncResult, setResyncResult] = useState<string | null>(initialResyncResult);

  async function handleForceResync() {
    await forceVaultResyncAction(setResyncing, setResyncResult, onToast);
  }

  // App rules state
  const [apps, setApps] = useState<AppRule[] | null>(null);
  // The App Rules summary card on this shell; AppsTab computes its own.
  const tracedCount = (apps ?? []).filter((a) => a.tracked).length;
  const mutedCount = (apps ?? []).length - tracedCount;
  const excludedCount = (s?.activity_excluded_apps ?? "")
    .split(",")
    .filter((x) => x.trim()).length;

  /** Local, optimistic edit; `save` is what persists it. */
  // The Whisper summary card on this shell mirrors AiTab's derived state.
  const wp: WhisperProgress | null = whisperProgress ?? s?.transcribe_progress ?? null;
  const cachedWhisperSet = new Set<string>([
    ...((s?.transcribe_cached_models as string[] | undefined) ?? []),
    ...(wp?.status === "ready" && wp.model ? [wp.model] : []),
  ]);

  const patch = useCallback((changes: Partial<Settings>) => {
    setS((prev) => (prev ? { ...prev, ...changes } : prev));
  }, []);

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

  async function save(changes: Record<string, unknown>, label = "settings saved") {
    if (!s) return;
    setSaving(true);
    // Optimistic: show the new value immediately, then reconcile with whatever
    // the server actually stored. Without the rollback, a rejected save left the
    // input showing a value that was never persisted.
    const previous = s;
    setS(applySettingsChange(previous, changes));
    try {
      setS(reconcileSettings(previous, previous, await api.updateSettings(changes)));
      onToast(label);
    } catch (e) {
      setS(reconcileSettings(previous, previous, null));
      onToast(errorMessage(e), "err");
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

  if (!s) {
    return (
      <div className="space-y-3 p-5">
        {[0, 1, 2].map((i) => (
          <div key={i} className="shimmer h-24 rounded-2xl" />
        ))}
      </div>
    );
  }



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
                {mutedCount} muted · {excludedCount} blocked
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

          {tab === "ai" && (
            <AiTab
              s={s}
              patch={patch}
              save={save}
              saving={saving}
              whisperProgress={whisperProgress}
              loadAll={loadAll}
            />
          )}

          {tab === "activity" && (
            <ActivityTab s={s} patch={patch} save={save} saving={saving} />
          )}

          {tab === "apps" && (
            <AppsTab apps={apps} toggleApp={toggleApp} bulkSetApps={bulkSetApps} />
          )}

          {tab === "vault" && (
            <VaultTab
              s={s}
              patch={patch}
              save={save}
              saving={saving}
              resyncing={resyncing}
              resyncResult={resyncResult}
              handleForceResync={handleForceResync}
              onToast={onToast}
            />
          )}

          {tab === "system" && (
            <SystemTab health={health} s={s} onToast={onToast} loadAll={loadAll} />
          )}
        </div>
      </div>
    </div>
  );
}

