import { useState } from "react";
import { ActivityIcon, FolderIcon, XIcon } from "../Icons";
import { inputCls, labelCls, type FormProps, Toggle } from "./shared";

/** Activity & Privacy tab: collector cadence, idle cutoff, blocklist, watch dirs. */
export default function ActivityTab({ s, patch, save }: FormProps) {
  const [newExcluded, setNewExcluded] = useState("");
  const [newWatchDir, setNewWatchDir] = useState("");

  const excludedList = (s.activity_excluded_apps || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  const watchDirsList = (s.activity_watch_dirs || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

  return (
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
                  onChange={(e) => patch({ activity_poll_secs: Number(e.target.value) })}
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
                        patch({ activity_poll_secs: sec });
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
                <label className={labelCls} htmlFor="retention-days">
                  History Retention (days)
                </label>
                <p className="mt-0.5 text-[11px] text-ink-400">
                  Window activity older than this is deleted on startup. Daily reports only
                  look back 24 hours.
                </p>
                <input
                  id="retention-days"
                  type="number"
                  min={1}
                  max={3650}
                  value={s.activity_retention_days}
                  onChange={(e) =>
                    patch({ activity_retention_days: Number(e.target.value) })
                  }
                  onBlur={() =>
                    void save(
                      { activity_retention_days: s.activity_retention_days },
                      "retention updated",
                    )
                  }
                  className={`${inputCls} font-mono`}
                />
                <div className="mt-2 flex gap-1.5">
                  {[7, 30, 90, 365].map((days) => (
                    <button
                      key={days}
                      onClick={() => {
                        patch({ activity_retention_days: days });
                        void save({ activity_retention_days: days }, `retention set to ${days}d`);
                      }}
                      className={`rounded-lg px-2.5 py-0.5 font-mono text-[10px] ${
                        s.activity_retention_days === days
                          ? "bg-ember-500/25 font-semibold text-ember-300"
                          : "bg-ink-850 text-ink-400 hover:text-ink-200"
                      }`}
                    >
                      {days}d
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border border-ink-800 bg-ink-950/50 p-3.5">
                <label className={labelCls} htmlFor="idle-cutoff">
                  Idle Cutoff (minutes cursor still)
                </label>
                <input
                  id="idle-cutoff"
                  type="number"
                  min={1}
                  max={60}
                  value={s.activity_idle_after_min}
                  onChange={(e) =>
                    patch({ activity_idle_after_min: Number(e.target.value) })
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
                        patch({ activity_idle_after_min: min });
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
                        patch({ activity_excluded_apps: next });
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
                      patch({ activity_excluded_apps: next });
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
                    patch({ activity_excluded_apps: next });
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
                        patch({ activity_watch_dirs: next });
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
                      patch({ activity_watch_dirs: next });
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
                    patch({ activity_watch_dirs: next });
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
  );
}
