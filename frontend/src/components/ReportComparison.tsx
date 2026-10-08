import { useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { diffStats, diffText } from "./textDiff";
import { BotIcon, CopyIcon } from "./Icons";
import type { DailyLog } from "../types";

interface Props {
  dayA: string;
  dayB: string;
  onDayAChange: (day: string) => void;
  onDayBChange: (day: string) => void;
  onClose: () => void;
  onToast: (msg: string, kind?: "ok" | "err") => void;
  refreshKey: number;
}

function shiftDay(day: string, delta: number): string {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

export default function ReportComparison({
  dayA,
  dayB,
  onDayAChange,
  onDayBChange,
  onClose,
  onToast,
  refreshKey,
}: Props) {
  const [logA, setLogA] = useState<DailyLog | null>(null);
  const [logB, setLogB] = useState<DailyLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.dailyLog(dayA), api.dailyLog(dayB)])
      .then(([a, b]) => {
        setLogA(a);
        setLogB(b);
      })
      .catch((err) => {
        onToast(err instanceof Error ? err.message : String(err), "err");
      })
      .finally(() => setLoading(false));
  }, [dayA, dayB, refreshKey, onToast]);

  const bodyA = logA?.edited_body ?? logA?.summary_md ?? "";
  const bodyB = logB?.edited_body ?? logB?.summary_md ?? "";
  const diffParts = showDiff ? diffText(bodyA, bodyB) : [];
  const stats = showDiff ? diffStats(diffParts) : null;

  async function copyReport(text: string) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      onToast("Report copied to clipboard");
    } catch {
      onToast("Failed to copy", "err");
    }
  }

  return (
    <div className="glass-studio glow-border flex h-full flex-col rounded-2xl p-4">
      {/* Comparison toolbar */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.08] pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-iris-500/20 text-iris-300 ring-1 ring-iris-500/30">
            <BotIcon className="h-3.5 w-3.5" />
          </div>
          <div>
            <h2 className="text-xs font-semibold text-ink-100">Side-by-Side Comparison</h2>
            <p className="font-mono text-[10px] text-ink-400">
              Comparing {dayA} with {dayB}
              {stats ? ` · +${stats.added} words / -${stats.removed} words` : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDiff(!showDiff)}
            className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
              showDiff
                ? "border-amber-400/50 bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30"
                : "border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/20 hover:text-ink-100"
            }`}
            title="Toggle word-level diff highlights"
          >
            {showDiff ? "Hide Word Diff" : "Show Word Diff"}
          </button>
          <button
            onClick={onClose}
            className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-400 hover:text-ink-200"
            aria-label="Exit side-by-side comparison"
          >
            Exit Comparison
          </button>
        </div>
      </div>

      {loading && (
        <p className="py-8 text-center text-xs text-ink-400">Loading daily reports for comparison…</p>
      )}

      {/* Side-by-side columns */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 md:grid-cols-2">
        {/* Column A */}
        <div className="flex flex-col rounded-xl border border-white/[0.06] bg-ink-950/40 p-3.5">
          <div className="mb-3 flex items-center justify-between border-b border-white/[0.06] pb-2">
            <div className="flex items-center gap-1 font-mono text-xs">
              <button
                onClick={() => onDayAChange(shiftDay(dayA, -1))}
                aria-label="Previous day A"
                className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-ink-300 hover:border-ember-400/40"
              >
                ‹
              </button>
              <span className="min-w-24 text-center font-semibold text-ink-100">{dayA}</span>
              <button
                onClick={() => onDayAChange(shiftDay(dayA, 1))}
                aria-label="Next day A"
                className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-ink-300 hover:border-ember-400/40"
              >
                ›
              </button>
            </div>
            <div className="flex items-center gap-1">
              {Boolean(logA?.edited) && (
                <span className="rounded bg-iris-500/15 px-1 py-0.5 text-[9px] font-medium text-iris-300">
                  Edited
                </span>
              )}
              <button
                onClick={() => void copyReport(bodyA)}
                disabled={!bodyA}
                className="rounded p-1 text-ink-400 hover:text-ink-200"
                title="Copy report A"
              >
                <CopyIcon className="h-3 w-3" />
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {showDiff ? (
              <div className="text-xs leading-relaxed font-mono whitespace-pre-wrap">
                {diffParts
                  .filter((p) => p.type !== "add")
                  .map((p, idx) => (
                    <span
                      key={idx}
                      className={
                        p.type === "del"
                          ? "bg-red-500/20 text-red-300 line-through rounded px-0.5"
                          : "text-ink-300"
                      }
                    >
                      {p.text}
                    </span>
                  ))}
              </div>
            ) : bodyA ? (
              <div
                className="digest-body text-xs leading-relaxed text-ink-200"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(bodyA) }}
              />
            ) : (
              <p className="text-xs text-ink-500 italic">No report written for {dayA}.</p>
            )}
          </div>
        </div>

        {/* Column B */}
        <div className="flex flex-col rounded-xl border border-white/[0.06] bg-ink-950/40 p-3.5">
          <div className="mb-3 flex items-center justify-between border-b border-white/[0.06] pb-2">
            <div className="flex items-center gap-1 font-mono text-xs">
              <button
                onClick={() => onDayBChange(shiftDay(dayB, -1))}
                aria-label="Previous day B"
                className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-ink-300 hover:border-ember-400/40"
              >
                ‹
              </button>
              <span className="min-w-24 text-center font-semibold text-ink-100">{dayB}</span>
              <button
                onClick={() => onDayBChange(shiftDay(dayB, 1))}
                aria-label="Next day B"
                className="rounded border border-ink-700 bg-ink-900 px-1.5 py-0.5 text-ink-300 hover:border-ember-400/40"
              >
                ›
              </button>
            </div>
            <div className="flex items-center gap-1">
              {Boolean(logB?.edited) && (
                <span className="rounded bg-iris-500/15 px-1 py-0.5 text-[9px] font-medium text-iris-300">
                  Edited
                </span>
              )}
              <button
                onClick={() => void copyReport(bodyB)}
                disabled={!bodyB}
                className="rounded p-1 text-ink-400 hover:text-ink-200"
                title="Copy report B"
              >
                <CopyIcon className="h-3 w-3" />
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {showDiff ? (
              <div className="text-xs leading-relaxed font-mono whitespace-pre-wrap">
                {diffParts
                  .filter((p) => p.type !== "del")
                  .map((p, idx) => (
                    <span
                      key={idx}
                      className={
                        p.type === "add"
                          ? "bg-emerald-500/20 text-emerald-300 rounded px-0.5 font-medium"
                          : "text-ink-300"
                      }
                    >
                      {p.text}
                    </span>
                  ))}
              </div>
            ) : bodyB ? (
              <div
                className="digest-body text-xs leading-relaxed text-ink-200"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(bodyB) }}
              />
            ) : (
              <p className="text-xs text-ink-500 italic">No report written for {dayB}.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
