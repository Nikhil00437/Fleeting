import { FolderIcon, LinkIcon, RefreshIcon } from "../Icons";
import { inputCls, labelCls, type FormProps, type ToastFn, Toggle } from "./shared";

interface Props extends FormProps {
  resyncing: boolean;
  resyncResult: string | null;
  handleForceResync: () => Promise<unknown>;
  onToast: ToastFn;
}

/** Vault & Ingestion tab: markdown mirror, resync, YouTube and notifications. */
export default function VaultTab({
  s,
  patch,
  save,
  saving,
  resyncing,
  resyncResult,
  handleForceResync,
}: Props) {
  return (
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

            {/* Watcher Status & Force Re-sync Action */}
            <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-ink-800 bg-ink-950/60 p-3.5">
              <div className="flex min-w-0 items-center gap-2">
                <span
                  data-testid="vault-status-pill"
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-xs ${
                    s.vault_sync
                      ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border border-ink-700 bg-ink-900 text-ink-400"
                  }`}
                >
                  {s.vault_sync
                    ? `🟢 Watching Vault (${s.vault_dir || "configured directory"})`
                    : "⚪ Sync Disabled"}
                </span>
              </div>
              <button
                type="button"
                onClick={handleForceResync}
                disabled={resyncing}
                className="inline-flex items-center gap-1.5 rounded-xl border border-ink-700 bg-ink-900 px-3 py-1.5 text-xs font-semibold text-ink-200 transition-colors hover:border-ember-400/40 hover:text-ink-100 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <RefreshIcon className={`h-3.5 w-3.5 ${resyncing ? "animate-spin" : ""}`} />
                <span>{resyncing ? "Re-syncing..." : "Force Vault Re-sync"}</span>
              </button>
            </div>

            {resyncResult && (
              <div
                data-testid="vault-resync-summary"
                className="rounded-xl border border-emerald-500/30 bg-emerald-950/20 px-3.5 py-2.5 font-mono text-xs text-emerald-300"
              >
                {resyncResult}
              </div>
            )}

            <div>
              <label className={labelCls}>Vault Directory Path</label>
              <div className="flex gap-2">
                <input
                  value={s.vault_dir}
                  onChange={(e) => patch({ vault_dir: e.target.value })}
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
                      patch({ yt_max_duration_min: Number(e.target.value) })
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
                          patch({ yt_max_duration_min: m });
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

                <div className="mt-4 border-t border-ink-800/80 pt-4">
                  <p className="text-xs font-semibold text-ink-100">
                    Nightly "what did I forget?"
                  </p>
                  <p className="text-[11px] text-ink-400">
                    Once a night, list the open loops still yours — overdue tasks and loose ends
                    from your reports. Nothing is invented; it only reads what you already wrote.
                  </p>
                </div>
                <Toggle
                  checked={s.notifications_nightly_nudge}
                  onChange={(v) =>
                    void save(
                      { notifications_nightly_nudge: v },
                      v ? "nightly nudge enabled" : "nightly nudge disabled",
                    )
                  }
                />
              </div>
            </div>
          </section>
        </div>
  );
}
