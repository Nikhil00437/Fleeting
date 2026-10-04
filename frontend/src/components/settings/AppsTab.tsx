import { useMemo, useState } from "react";
import { SearchIcon, XIcon } from "../Icons";
import { StackBar } from "../charts";
import { appColor, appMonogram, fmtSecs, prettyAppName } from "../../apps";
import { Toggle } from "./shared";
import type { AppRule } from "../../types";

interface Props {
  apps: AppRule[] | null;
  toggleApp: (app: AppRule) => Promise<void>;
  bulkSetApps: (tracked: boolean, targets: AppRule[]) => Promise<void>;
}

/** App Rules tab: per-app tracing switches with bulk trace/mute. */
export default function AppsTab({ apps, toggleApp, bulkSetApps }: Props) {
  const [appQuery, setAppQuery] = useState("");
  const [appFilter, setAppFilter] = useState<"all" | "traced" | "muted">("all");
  const [appSort, setAppSort] = useState<"time" | "sessions" | "name">("time");

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

  const tracedCount = (apps ?? []).filter((a) => a.tracked).length;
  const mutedCount = (apps ?? []).length - tracedCount;
  const maxAppSecs = Math.max(...(apps ?? []).map((a) => a.seconds), 1);

  return (
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
  );
}
