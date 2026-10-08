import { useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { CopyIcon, RefreshIcon, SparkIcon } from "./Icons";
import type { StandupOut } from "../types";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  day?: string;
}

export default function StandupModal({ isOpen, onClose, onToast, day }: Props) {
  const [data, setData] = useState<StandupOut | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    setLoading(true);
    api
      .standup(day)
      .then((res) => {
        setData(res);
      })
      .catch((err) => {
        onToast(err instanceof Error ? err.message : String(err), "err");
      })
      .finally(() => setLoading(false));
  }, [isOpen, day, onToast]);

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

  async function handleRegenerate() {
    setBusy(true);
    try {
      const res = await api.generateStandup(day);
      setData(res);
      onToast("Standup refreshed");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setBusy(false);
    }
  }

  async function handleCopy() {
    if (!data?.standup_md) return;
    try {
      await navigator.clipboard.writeText(data.standup_md);
      setCopied(true);
      onToast("Standup copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      onToast("Failed to copy to clipboard", "err");
    }
  }

  async function handleSaveAsNote() {
    if (!data?.standup_md) return;
    setSavingNote(true);
    try {
      await api.saveStandupAsNote(data.day, data.standup_md);
      onToast("Saved standup as note");
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
      aria-labelledby="standup-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="glass-studio glow-border flex max-h-[88vh] w-full max-w-2xl flex-col rounded-2xl p-5 shadow-2xl">
        {/* Header */}
        <div className="mb-4 flex items-center justify-between border-b border-white/[0.08] pb-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30">
              <SparkIcon className="h-4 w-4" />
            </div>
            <div>
              <h2 id="standup-modal-title" className="text-sm font-semibold text-ink-100">
                Daily Standup
              </h2>
              <p className="font-mono text-[11px] text-ink-400">
                {data ? `${data.day} (vs. ${data.previous_day})` : "Generating…"}
                {data?.model ? ` · ${data.model === "fallback" ? "offline heuristics" : data.model}` : ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => void handleRegenerate()}
              disabled={busy || loading}
              className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Regenerate standup"
            >
              <RefreshIcon className="h-3 w-3" />
              {busy ? "Writing…" : "Regen"}
            </button>
            <button
              onClick={() => void handleCopy()}
              disabled={!data?.standup_md}
              className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Copy markdown to clipboard"
            >
              <CopyIcon className="h-3 w-3" />
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={() => void handleSaveAsNote()}
              disabled={!data?.standup_md || savingNote}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
              title="Save standup as a markdown note"
            >
              {savingNote ? "Saving…" : "Save Note"}
            </button>
            <button
              onClick={onClose}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-400 hover:text-ink-200"
              aria-label="Close standup dialog"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Quick summary metrics */}
        {data && (
          <div className="mb-4 grid grid-cols-3 gap-2 font-mono text-xs">
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Yesterday</p>
              <p className="font-semibold text-ink-100">{data.yesterday_tasks?.length ?? 0} completed</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Today</p>
              <p className="font-semibold text-ink-100">{data.today_tasks?.length ?? 0} planned</p>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2">
              <p className="micro-label !text-[9px]">Blockers</p>
              <p className="font-semibold text-ink-100">{data.blockers?.length ?? 0} open</p>
            </div>
          </div>
        )}

        {/* Body */}
        <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-white/[0.06] bg-ink-950/40 p-4">
          {loading ? (
            <p className="text-xs text-ink-400">Synthesizing yesterday's completions, today's tasks and blockers…</p>
          ) : data?.standup_md ? (
            <div
              className="digest-body text-sm leading-relaxed text-ink-200"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(data.standup_md) }}
            />
          ) : (
            <p className="text-xs text-ink-400">No standup generated yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
