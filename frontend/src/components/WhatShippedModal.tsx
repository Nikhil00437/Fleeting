import { useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { CheckIcon, CopyIcon, SparkIcon, XIcon } from "./Icons";
import type { WhatShippedOut } from "../types";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  initialWeek?: string;
}

function shiftWeek(weekStart: string, deltaWeeks: number): string {
  const d = new Date(`${weekStart}T12:00:00`);
  d.setDate(d.getDate() + deltaWeeks * 7);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function WhatShippedModal({
  isOpen,
  onClose,
  onToast,
  initialWeek,
}: Props) {
  const [week, setWeek] = useState(initialWeek || "");
  const [data, setData] = useState<WhatShippedOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [activeTab, setActiveTab] = useState<"changelog" | "commits" | "tasks" | "notes">("changelog");

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    api.whatShipped(week || undefined)
      .then((res) => {
        setData(res);
        if (!week) setWeek(res.week_start);
      })
      .catch((err) => {
        onToast(err instanceof Error ? err.message : String(err), "err");
      })
      .finally(() => setLoading(false));
  }, [isOpen, week, onToast]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  async function handleCopy() {
    if (!data?.markdown) return;
    try {
      await navigator.clipboard.writeText(data.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onToast("Weekly changelog copied to clipboard");
    } catch {
      onToast("Failed to copy changelog", "err");
    }
  }

  async function handleSaveAsNote() {
    if (!data) return;
    setSavingNote(true);
    try {
      const res = await api.saveWhatShippedAsNote(data.week_start, data.markdown);
      if (res.ok) {
        onToast("Saved What Shipped changelog as note");
      }
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setSavingNote(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-labelledby="what-shipped-title"
    >
      <div className="flex h-[88vh] max-h-[820px] w-full max-w-4xl flex-col rounded-2xl border border-white/10 bg-ink-900 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.08] px-5 py-3.5 bg-ink-950/40">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 text-emerald-300 ring-1 ring-white/10">
              <SparkIcon className="h-4 w-4" />
            </div>
            <div>
              <h2 id="what-shipped-title" className="text-sm font-semibold text-ink-100">
                What Shipped
              </h2>
              <p className="text-[11px] text-ink-400">
                Weekly synthesis combining commits, completed tasks, and notes (#166).
              </p>
            </div>
          </div>

          {/* Week Stepper & Close */}
          <div className="flex items-center gap-2">
            {data && (
              <div className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1">
                <button
                  onClick={() => setWeek(shiftWeek(data.week_start, -1))}
                  aria-label="Previous week"
                  className="rounded px-1.5 py-0.5 text-xs text-ink-400 hover:text-ink-200"
                >
                  ‹
                </button>
                <span className="font-mono text-xs text-ink-200 min-w-28 text-center">
                  {data.week_start}
                </span>
                <button
                  onClick={() => setWeek(shiftWeek(data.week_start, 1))}
                  aria-label="Next week"
                  className="rounded px-1.5 py-0.5 text-xs text-ink-400 hover:text-ink-200"
                >
                  ›
                </button>
              </div>
            )}
            <button
              onClick={onClose}
              aria-label="Close what shipped modal"
              className="rounded-lg p-1 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Counts summary bar */}
        {data && (
          <div className="flex items-center justify-between border-b border-white/[0.06] bg-ink-950/20 px-5 py-2 text-xs">
            <div className="flex items-center gap-3">
              <span className="font-semibold text-emerald-300">
                {data.counts.total} items shipped
              </span>
              <span className="text-ink-500">·</span>
              <span className="text-ink-400">{data.counts.commits} commits</span>
              <span className="text-ink-500">·</span>
              <span className="text-ink-400">{data.counts.tasks} tasks closed</span>
              <span className="text-ink-500">·</span>
              <span className="text-ink-400">{data.counts.notes} captures</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.02] px-2.5 py-1 text-xs text-ink-300 hover:bg-white/[0.05]"
              >
                {copied ? <CheckIcon className="h-3.5 w-3.5 text-emerald-400" /> : <CopyIcon className="h-3.5 w-3.5" />}
                <span>{copied ? "Copied" : "Copy Changelog"}</span>
              </button>
              <button
                onClick={handleSaveAsNote}
                disabled={savingNote}
                className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
              >
                Save as Note
              </button>
            </div>
          </div>
        )}

        {/* Tab Switcher */}
        <div className="flex items-center gap-1 border-b border-white/[0.06] px-5 py-2 bg-ink-900">
          <button
            onClick={() => setActiveTab("changelog")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "changelog" ? "bg-white/[0.08] text-ink-100" : "text-ink-400 hover:text-ink-200"
            }`}
          >
            Changelog Preview
          </button>
          <button
            onClick={() => setActiveTab("commits")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "commits" ? "bg-white/[0.08] text-ink-100" : "text-ink-400 hover:text-ink-200"
            }`}
          >
            Commits ({data?.counts.commits || 0})
          </button>
          <button
            onClick={() => setActiveTab("tasks")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "tasks" ? "bg-white/[0.08] text-ink-100" : "text-ink-400 hover:text-ink-200"
            }`}
          >
            Tasks ({data?.counts.tasks || 0})
          </button>
          <button
            onClick={() => setActiveTab("notes")}
            className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
              activeTab === "notes" ? "bg-white/[0.08] text-ink-100" : "text-ink-400 hover:text-ink-200"
            }`}
          >
            Captures ({data?.counts.notes || 0})
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-5 text-xs">
          {loading && !data && (
            <div className="flex h-full items-center justify-center">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-emerald-400 border-t-transparent" />
            </div>
          )}

          {data && (
            <>
              {activeTab === "changelog" && (
                <div
                  className="markdown-body leading-relaxed text-ink-200"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(data.markdown) }}
                />
              )}

              {activeTab === "commits" && (
                <div className="flex flex-col gap-4">
                  {Object.keys(data.commits_by_repo).length === 0 ? (
                    <p className="text-ink-500 py-6 text-center">No git commits recorded in this week.</p>
                  ) : (
                    Object.entries(data.commits_by_repo).map(([repoName, repoCommits]) => (
                      <div key={repoName} className="rounded-xl border border-white/[0.06] bg-ink-950/40 p-3">
                        <div className="mb-2 flex items-center justify-between border-b border-white/[0.04] pb-1.5">
                          <span className="font-semibold text-emerald-300">{repoName}</span>
                          <span className="font-mono text-[10px] text-ink-500">{repoCommits.length} commits</span>
                        </div>
                        <ul className="flex flex-col gap-1.5" role="list">
                          {repoCommits.map((c, idx) => (
                            <li key={idx} className="flex items-baseline justify-between gap-2 text-ink-200">
                              <span className="truncate">{c.subject}</span>
                              {c.committed_at && (
                                <span className="font-mono text-[10px] text-ink-500 shrink-0">
                                  {c.committed_at.slice(5, 10)}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))
                  )}
                </div>
              )}

              {activeTab === "tasks" && (
                <div className="flex flex-col gap-2">
                  {data.completed_tasks.length === 0 ? (
                    <p className="text-ink-500 py-6 text-center">No tasks completed in this week.</p>
                  ) : (
                    data.completed_tasks.map((t) => (
                      <div
                        key={t.id}
                        className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span className="font-medium text-ink-100">{t.text}</span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] text-ink-400 font-mono">
                          {t.priority && (
                            <span className="rounded bg-white/[0.04] px-1 py-0.5">{t.priority}</span>
                          )}
                          {t.repo && <span>· {t.repo}</span>}
                          {t.completed_at && <span>· {t.completed_at.slice(5, 10)}</span>}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {activeTab === "notes" && (
                <div className="flex flex-col gap-2">
                  {data.notes.length === 0 ? (
                    <p className="text-ink-500 py-6 text-center">No captures created in this week.</p>
                  ) : (
                    data.notes.map((n) => (
                      <div
                        key={n.id}
                        className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-ink-950/40 p-2.5"
                      >
                        <div className="flex items-center gap-2">
                          <span className="rounded bg-white/[0.04] px-1 py-0.5 text-[10px] text-ink-400">
                            {n.type}
                          </span>
                          <span className="font-medium text-ink-100">{n.title}</span>
                        </div>
                        {n.tags.length > 0 && (
                          <div className="flex items-center gap-1 text-[10px] text-ink-400">
                            {n.tags.map((t) => (
                              <span key={t} className="rounded bg-iris-500/10 px-1 py-0.5 text-iris-300">
                                #{t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
