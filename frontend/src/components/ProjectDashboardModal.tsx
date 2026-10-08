import { useEffect, useState } from "react";
import { api } from "../api";
import { FolderIcon, XIcon } from "./Icons";
import type { ProjectDashboard, ProjectSummary } from "../types";

function fmtSecs(sec: number): string {
  if (sec <= 0) return "0m";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

interface ProjectDashboardModalProps {
  initialProject?: string | null;
  onClose: () => void;
  onOpenNote?: (id: string) => void;
}

export function ProjectDashboardModal({
  initialProject,
  onClose,
  onOpenNote,
}: ProjectDashboardModalProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>(initialProject || "");
  const [windowDays, setWindowDays] = useState<number>(30);
  const [dashboard, setDashboard] = useState<ProjectDashboard | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Load project list
  useEffect(() => {
    api
      .projectsSummary()
      .then((res) => {
        setProjects(res.projects);
        if (!selectedProject && res.projects.length > 0) {
          setSelectedProject(res.projects[0].project);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  // Load dashboard when project or window changes
  useEffect(() => {
    if (!selectedProject) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .projectDashboard(selectedProject, windowDays)
      .then((data) => {
        setDashboard(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [selectedProject, windowDays]);

  const maxDailySeconds =
    dashboard?.daily_breakdown.reduce((max, d) => Math.max(max, d.seconds), 0) || 1;

  return (
    <div
      role="dialog"
      aria-label="Project Dashboard"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
    >
      <div className="glass-studio flex max-h-[90vh] w-full max-w-4xl flex-col rounded-2xl border border-white/[0.08] bg-ink-950/95 shadow-2xl">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] p-4">
          <div className="flex items-center gap-2">
            <FolderIcon className="h-5 w-5 text-ember-400" />
            <h2 className="text-sm font-semibold text-ink-100">Project Dashboard</h2>
            <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
              #167
            </span>
          </div>

          <div className="flex items-center gap-3">
            {/* Project Selector */}
            {projects.length > 0 ? (
              <select
                aria-label="Select project"
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
                className="rounded-lg border border-white/[0.1] bg-ink-900 px-2.5 py-1 text-xs font-medium text-ink-200 outline-hidden hover:border-ember-500/50"
              >
                {projects.map((p) => (
                  <option key={p.project} value={p.project}>
                    {p.project} ({fmtSecs(p.total_seconds)})
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-xs text-ink-500">No projects</span>
            )}

            {/* Time Window */}
            <div className="flex rounded-lg border border-white/[0.06] bg-ink-900/80 p-0.5 text-[10.5px]">
              {([7, 14, 30, 90] as const).map((days) => (
                <button
                  key={days}
                  onClick={() => setWindowDays(days)}
                  className={`rounded-md px-2 py-0.5 font-mono transition-colors ${
                    windowDays === days
                      ? "bg-ember-500/20 font-semibold text-ember-300"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  {days}d
                </button>
              ))}
            </div>

            <button
              onClick={onClose}
              aria-label="Close project dashboard"
              className="rounded-lg p-1 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-xs">
          {loading ? (
            <div className="py-12 text-center text-ink-500 animate-pulse">
              Loading project dashboard...
            </div>
          ) : error ? (
            <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-center text-red-300">
              {error}
            </div>
          ) : !dashboard || !selectedProject ? (
            <div className="py-12 text-center text-ink-500">
              No project selected or detected yet.
            </div>
          ) : (
            <>
              {/* KPIs */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-center">
                  <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                    Total Time
                  </div>
                  <div className="mt-1 font-mono text-base font-semibold text-ember-300">
                    {fmtSecs(dashboard.total_seconds)}
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-center">
                  <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                    Last {windowDays} Days
                  </div>
                  <div className="mt-1 font-mono text-base font-semibold text-iris-300">
                    {fmtSecs(dashboard.window_seconds)}
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-center">
                  <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                    Active Days
                  </div>
                  <div className="mt-1 font-mono text-base font-semibold text-emerald-300">
                    {dashboard.active_days}
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-center">
                  <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                    Tasks
                  </div>
                  <div className="mt-1 font-mono text-base font-semibold text-amber-300">
                    {dashboard.tasks.completed}/{dashboard.tasks.total}
                  </div>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-center">
                  <div className="text-[10px] text-ink-400 uppercase tracking-wider">
                    Commits
                  </div>
                  <div className="mt-1 font-mono text-base font-semibold text-cyan-300">
                    {dashboard.commits.length}
                  </div>
                </div>
              </div>

              {/* Daily Activity Spark Bar */}
              {dashboard.daily_breakdown.length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="micro-label">Daily Focus (Last {windowDays}d)</span>
                    <span className="font-mono text-[10px] text-ink-400">
                      {dashboard.daily_breakdown.length} active day
                      {dashboard.daily_breakdown.length === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="flex h-16 items-end gap-1 overflow-x-auto pt-2">
                    {dashboard.daily_breakdown.map((d) => {
                      const pct = Math.max(8, Math.round((d.seconds / maxDailySeconds) * 100));
                      return (
                        <div
                          key={d.day}
                          className="group relative flex flex-1 min-w-[12px] flex-col items-center"
                        >
                          <div
                            style={{ height: `${pct}%` }}
                            className="w-full rounded-t-xs bg-ember-500/70 transition-all group-hover:bg-ember-400"
                            title={`${d.day}: ${fmtSecs(d.seconds)}`}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Two columns: Apps & Branches vs Commits & Tasks */}
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {/* Apps & Branches */}
                <div className="space-y-4">
                  {/* Top Applications */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="micro-label mb-2">Applications</div>
                    {dashboard.apps.length === 0 ? (
                      <div className="py-2 text-ink-500">No application breakdown</div>
                    ) : (
                      <div className="space-y-2">
                        {dashboard.apps.slice(0, 6).map((app) => (
                          <div key={app.app} className="space-y-1">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-medium text-ink-200">{app.app}</span>
                              <span className="font-mono text-ink-400">
                                {fmtSecs(app.seconds)} ({app.percent}%)
                              </span>
                            </div>
                            <div className="h-1.5 w-full rounded-full bg-ink-900">
                              <div
                                style={{ width: `${Math.min(100, app.percent)}%` }}
                                className="h-full rounded-full bg-iris-500"
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Git Branches */}
                  {dashboard.branches.length > 0 && (
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                      <div className="micro-label mb-2">Branches Worked On</div>
                      <div className="flex flex-wrap gap-1.5">
                        {dashboard.branches.map((b) => (
                          <span
                            key={b.branch}
                            className="rounded-lg border border-white/[0.06] bg-ink-900/60 px-2 py-1 font-mono text-[10.5px] text-ink-300"
                            title={fmtSecs(b.seconds)}
                          >
                            {b.branch}
                            <span className="ml-1 text-ink-500">({fmtSecs(b.seconds)})</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Linked Notes */}
                  {dashboard.notes.length > 0 && (
                    <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                      <div className="micro-label mb-2">Linked Notes</div>
                      <div className="space-y-1.5">
                        {dashboard.notes.map((n) => (
                          <div
                            key={n.id}
                            onClick={() => onOpenNote?.(n.id)}
                            className="flex cursor-pointer items-center justify-between rounded-lg p-1.5 transition-colors hover:bg-white/[0.04]"
                          >
                            <span className="font-medium text-ink-200 truncate hover:text-ember-300">
                              {n.title}
                            </span>
                            <span className="font-mono text-[10px] text-ink-500">
                              {n.created_at.slice(0, 10)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Commits & Tasks */}
                <div className="space-y-4">
                  {/* Tasks */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="micro-label mb-2">
                      Tasks ({dashboard.tasks.completed}/{dashboard.tasks.total})
                    </div>
                    {dashboard.tasks.items.length === 0 ? (
                      <div className="py-2 text-ink-500">No linked tasks for this project</div>
                    ) : (
                      <div className="max-h-48 space-y-1.5 overflow-y-auto pr-1">
                        {dashboard.tasks.items.map((t) => (
                          <div
                            key={t.id}
                            className="flex items-start gap-2 rounded-lg p-1.5 transition-colors hover:bg-white/[0.02]"
                          >
                            <input
                              type="checkbox"
                              checked={!!t.done}
                              readOnly
                              className="mt-0.5 rounded-xs accent-emerald-500"
                            />
                            <div className="min-w-0 flex-1">
                              <p
                                className={`text-xs ${
                                  t.done ? "line-through text-ink-500" : "text-ink-200"
                                }`}
                              >
                                {t.text}
                              </p>
                              {(t.estimate_min || t.spent_min) && (
                                <div className="mt-0.5 font-mono text-[10px] text-ink-400">
                                  {t.spent_min ? `${t.spent_min}m spent` : ""}
                                  {t.estimate_min ? ` / ${t.estimate_min}m est` : ""}
                                </div>
                              )}
                            </div>
                            <span className="rounded-xs bg-white/[0.06] px-1 py-0.5 font-mono text-[9px] text-ink-400">
                              {t.priority}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Commits */}
                  <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="micro-label mb-2">Recent Commits ({dashboard.commits.length})</div>
                    {dashboard.commits.length === 0 ? (
                      <div className="py-2 text-ink-500">No commits recorded for this project</div>
                    ) : (
                      <div className="max-h-48 space-y-1.5 overflow-y-auto pr-1">
                        {dashboard.commits.map((c, i) => (
                          <div key={i} className="rounded-lg p-1.5 text-xs hover:bg-white/[0.02]">
                            <div className="font-medium text-ink-200">{c.subject}</div>
                            <div className="mt-0.5 flex items-center justify-between font-mono text-[10px] text-ink-500">
                              <span>{c.author || "Unknown"}</span>
                              <span>{c.committed_at.slice(0, 10)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
