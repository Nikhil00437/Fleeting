import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fmtSecs } from "../apps";
import { renderMarkdown } from "../markdown";
import { CopyIcon, RefreshIcon, SparkIcon } from "./Icons";
import type { PeriodicReviewOut } from "../types";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
}

function defaultPeriodFor(kind: "month" | "quarter" | "year"): string {
  const d = new Date();
  const year = d.getFullYear();
  if (kind === "year") return String(year);
  if (kind === "quarter") {
    const q = Math.floor(d.getMonth() / 3) + 1;
    return `${year}-Q${q}`;
  }
  return `${year}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function PeriodicReviewModal({ isOpen, onClose, onToast }: Props) {
  const [kind, setKind] = useState<"month" | "quarter" | "year">("month");
  const [period, setPeriod] = useState(() => defaultPeriodFor("month"));
  const [data, setData] = useState<PeriodicReviewOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(
    (k: "month" | "quarter" | "year", p: string) => {
      setLoading(true);
      api
        .periodicReview(k, p)
        .then((res) => {
          setData(res);
        })
        .catch((err) => {
          onToast(err instanceof Error ? err.message : String(err), "err");
        })
        .finally(() => setLoading(false));
    },
    [onToast],
  );

  useEffect(() => {
    if (!isOpen) return;
    load(kind, period);
  }, [isOpen, kind, period, load]);

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

  function switchKind(newKind: "month" | "quarter" | "year") {
    setKind(newKind);
    const newPeriod = defaultPeriodFor(newKind);
    setPeriod(newPeriod);
  }

  function stepPeriod(delta: -1 | 1) {
    if (kind === "year") {
      const yr = parseInt(period, 10) || new Date().getFullYear();
      setPeriod(String(yr + delta));
    } else if (kind === "quarter") {
      const [yrStr, qStr] = period.split("-Q");
      let yr = parseInt(yrStr, 10);
      let q = parseInt(qStr, 10) + delta;
      if (q < 1) {
        q = 4;
        yr -= 1;
      } else if (q > 4) {
        q = 1;
        yr += 1;
      }
      setPeriod(`${yr}-Q${q}`);
    } else {
      const [yrStr, moStr] = period.split("-");
      let yr = parseInt(yrStr, 10);
      let mo = parseInt(moStr, 10) + delta;
      if (mo < 1) {
        mo = 12;
        yr -= 1;
      } else if (mo > 12) {
        mo = 1;
        yr += 1;
      }
      setPeriod(`${yr}-${String(mo).padStart(2, "0")}`);
    }
  }

  async function handleCopy() {
    if (!data?.review_md) return;
    try {
      await navigator.clipboard.writeText(data.review_md);
      setCopied(true);
      onToast("Review copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      onToast("Failed to copy to clipboard", "err");
    }
  }

  async function handleSaveAsNote() {
    if (!data?.review_md) return;
    setSavingNote(true);
    try {
      await api.savePeriodicReviewAsNote(data.kind, data.period, data.review_md, data.title);
      onToast("Saved review as note");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setSavingNote(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="review-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="glass-studio glow-border flex max-h-[88vh] w-full max-w-3xl flex-col rounded-2xl p-5 shadow-2xl">
        {/* Header */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.08] pb-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-purple-500/20 text-purple-300 ring-1 ring-purple-500/30">
              <SparkIcon className="h-4 w-4" />
            </div>
            <div>
              <h2 id="review-modal-title" className="text-sm font-semibold text-ink-100">
                {data?.title || "Periodic Review"}
              </h2>
              <p className="font-mono text-[11px] text-ink-400">
                {data?.start_date} → {data?.end_date}
                {data?.model ? ` · ${data.model === "fallback" ? "offline heuristics" : data.model}` : ""}
              </p>
            </div>
          </div>

          {/* Kind selector pills */}
          <div className="flex items-center gap-1 rounded-lg border border-white/[0.08] bg-black/40 p-0.5 text-xs">
            <button
              onClick={() => switchKind("month")}
              className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                kind === "month" ? "bg-white/15 text-ink-100" : "text-ink-400 hover:text-ink-200"
              }`}
            >
              Month
            </button>
            <button
              onClick={() => switchKind("quarter")}
              className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                kind === "quarter" ? "bg-white/15 text-ink-100" : "text-ink-400 hover:text-ink-200"
              }`}
            >
              Quarter
            </button>
            <button
              onClick={() => switchKind("year")}
              className={`rounded-md px-2.5 py-1 font-medium transition-colors ${
                kind === "year" ? "bg-white/15 text-ink-100" : "text-ink-400 hover:text-ink-200"
              }`}
            >
              Year (Wrapped)
            </button>
          </div>

          <div className="flex items-center gap-1.5">
            <div className="flex items-center gap-1 font-mono text-xs">
              <button
                onClick={() => stepPeriod(-1)}
                aria-label="Previous period"
                className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 text-ink-300 hover:border-ember-400/40"
              >
                ‹
              </button>
              <span className="min-w-20 text-center text-ink-200">{period}</span>
              <button
                onClick={() => stepPeriod(1)}
                aria-label="Next period"
                className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 text-ink-300 hover:border-ember-400/40"
              >
                ›
              </button>
            </div>

            <button
              onClick={() => load(kind, period)}
              disabled={loading}
              className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Refresh review"
            >
              <RefreshIcon className="h-3 w-3" />
              {loading ? "…" : "Regen"}
            </button>
            <button
              onClick={() => void handleCopy()}
              disabled={!data?.review_md}
              className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Copy markdown to clipboard"
            >
              <CopyIcon className="h-3 w-3" />
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={() => void handleSaveAsNote()}
              disabled={!data?.review_md || savingNote}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Save review as note"
            >
              {savingNote ? "Saving…" : "Save Note"}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-400 hover:text-ink-200"
              aria-label="Close review dialog"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Quick summary metrics */}
        {data && (
          <div className="mb-4 grid grid-cols-4 gap-2 font-mono text-xs">
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Focus</p>
              <p className="font-semibold text-ink-100">{fmtSecs(data.metrics.total_seconds)}</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Active days</p>
              <p className="font-semibold text-ink-100">{data.metrics.active_days}</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Tasks checked</p>
              <p className="font-semibold text-ink-100">{data.metrics.completed_tasks_count}</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Weekly digests</p>
              <p className="font-semibold text-ink-100">{data.metrics.weekly_logs_count}</p>
            </div>
          </div>
        )}

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/[0.06] bg-ink-950/40 p-4">
          {loading ? (
            <p className="text-xs text-ink-400">Synthesizing review from stored weekly digests and telemetry…</p>
          ) : data?.review_md ? (
            <div
              className="digest-body text-sm leading-relaxed text-ink-200"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(data.review_md) }}
            />
          ) : (
            <p className="text-xs text-ink-400">No review generated yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
