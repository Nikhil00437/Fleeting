import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { UnfinishedThread } from "../types";
import { CheckIcon, PlusIcon, TrashIcon } from "./Icons";

interface Props {
  onToast?: (message: string, kind?: "ok" | "err") => void;
  refreshKey?: number;
}

export default function UnfinishedThreadsCard({ onToast, refreshKey }: Props) {
  const [threads, setThreads] = useState<UnfinishedThread[] | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const load = useCallback(() => {
    api.unfinishedThreads()
      .then(setThreads)
      .catch((e) => onToast?.(String(e), "err"));
  }, [onToast]);

  useEffect(load, [load, refreshKey]);

  async function handleResolve(thread: UnfinishedThread) {
    setActionLoading(thread.id);
    try {
      await api.resolveThread(thread.id, "resolve");
      setThreads((prev) => (prev ? prev.filter((t) => t.id !== thread.id) : []));
      onToast?.("Thread marked resolved");
    } catch (e) {
      onToast?.(String(e), "err");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleDismiss(thread: UnfinishedThread) {
    setActionLoading(thread.id);
    try {
      await api.resolveThread(thread.id, "dismiss");
      setThreads((prev) => (prev ? prev.filter((t) => t.id !== thread.id) : []));
      onToast?.("Thread dismissed");
    } catch (e) {
      onToast?.(String(e), "err");
    } finally {
      setActionLoading(null);
    }
  }

  async function handleConvertToTask(thread: UnfinishedThread) {
    setActionLoading(thread.id);
    try {
      await api.convertThreadToTask(thread.id, thread.text);
      setThreads((prev) => (prev ? prev.filter((t) => t.id !== thread.id) : []));
      onToast?.("Converted thread to task");
    } catch (e) {
      onToast?.(String(e), "err");
    } finally {
      setActionLoading(null);
    }
  }

  if (!threads) return <div className="shimmer h-32 rounded-2xl" />;

  return (
    <section className="glass-studio rounded-2xl p-4" aria-label="Unfinished Threads">
      <div className="mb-2.5 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <span className="micro-label">Unfinished Threads</span>
          <span className="font-mono text-[10px] text-ink-500">
            {threads.length} thread{threads.length === 1 ? "" : "s"}
          </span>
        </div>
        <span className="text-[10px] text-ink-500">
          Persistent questions & blockers from reports
        </span>
      </div>

      {threads.length === 0 ? (
        <p className="text-[11px] text-ink-500">
          All caught up! No unresolved threads or blockers from recent reports.
        </p>
      ) : (
        <ul className="flex flex-col gap-2" role="list">
          {threads.map((thread) => {
            const isLoading = actionLoading === thread.id;
            return (
              <li
                key={thread.id}
                className="group flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5 transition-colors hover:border-white/10"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-ink-100">{thread.text}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-ink-400">
                    <span className="font-mono text-ink-500">{thread.source_day}</span>
                    <span>·</span>
                    <span className="rounded bg-white/[0.04] px-1 py-0.5 text-ink-400">
                      {thread.source_type === "task" ? "task" : "report digest"}
                    </span>
                    {thread.age_days > 0 && (
                      <>
                        <span>·</span>
                        <span className="text-amber-400/80">{thread.age_days}d open</span>
                      </>
                    )}
                    {thread.waiting_for && (
                      <span className="rounded bg-blue-500/10 px-1 py-0.5 text-blue-300">
                        waiting: {thread.waiting_for}
                      </span>
                    )}
                    {thread.blocked_by && (
                      <span className="rounded bg-rose-500/10 px-1 py-0.5 text-rose-300">
                        blocked by: {thread.blocked_by}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleConvertToTask(thread)}
                    disabled={isLoading}
                    aria-label={`Convert "${thread.text}" to task`}
                    className="flex items-center gap-1 rounded-lg border border-ember-500/30 bg-ember-500/10 px-2 py-1 text-[11px] font-medium text-ember-300 transition-colors hover:bg-ember-500/20 disabled:opacity-40"
                    title="Convert to action item in inbox"
                  >
                    <PlusIcon className="h-3 w-3" />
                    <span>To Task</span>
                  </button>
                  <button
                    onClick={() => handleResolve(thread)}
                    disabled={isLoading}
                    aria-label={`Mark "${thread.text}" as resolved`}
                    className="flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
                    title="Mark resolved"
                  >
                    <CheckIcon className="h-3 w-3" />
                    <span>Resolved</span>
                  </button>
                  <button
                    onClick={() => handleDismiss(thread)}
                    disabled={isLoading}
                    aria-label={`Dismiss "${thread.text}"`}
                    className="rounded-lg p-1 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200 disabled:opacity-40"
                    title="Dismiss without converting"
                  >
                    <TrashIcon className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
