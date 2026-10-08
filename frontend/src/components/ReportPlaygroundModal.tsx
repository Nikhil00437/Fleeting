import { useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { BotIcon, CheckIcon, CopyIcon, SparkIcon, XIcon } from "./Icons";
import type { ReportPlaygroundResult } from "../types";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  initialDay?: string;
}

function shiftDay(day: string, delta: number): string {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

const PROMPT_PRESETS = [
  {
    label: "Code & Architecture",
    prompt: "Focus strictly on software engineering, code changes, modified files, and commits. Omit casual browsing.",
  },
  {
    label: "Crisp Bullets (≤4)",
    prompt: "Produce at most 4 concise, high-impact bullet points summarizing the entire day. No filler or pleasantries.",
  },
  {
    label: "Client / Stakeholder",
    prompt: "Frame the summary for external stakeholders: emphasize completed deliverables, milestones, and roadmaps.",
  },
];

export default function ReportPlaygroundModal({
  isOpen,
  onClose,
  onToast,
  initialDay,
}: Props) {
  const yesterday = shiftDay(todayLocal(), -1);
  const [day, setDay] = useState(initialDay || yesterday);
  const [promptOverride, setPromptOverride] = useState("");
  const [tone, setTone] = useState<"balanced" | "terse" | "narrative" | "standup">("balanced");
  const [length, setLength] = useState<"short" | "medium" | "long">("medium");
  const [highlightsOnly, setHighlightsOnly] = useState(false);
  const [questionsForTomorrow, setQuestionsForTomorrow] = useState(false);

  const [activeTab, setActiveTab] = useState<"preview" | "prompt" | "transcript">("preview");
  const [result, setResult] = useState<ReportPlaygroundResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [copied, setCopied] = useState(false);

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

  async function handleRunTest() {
    setLoading(true);
    try {
      const res = await api.reportPlayground({
        day,
        prompt_override: promptOverride.trim() || undefined,
        tone,
        length,
        highlights_only: highlightsOnly,
        questions_for_tomorrow: questionsForTomorrow,
      });
      setResult(res);
      setActiveTab("preview");
      onToast("Playground test completed");
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!result?.preview_md) return;
    try {
      await navigator.clipboard.writeText(result.preview_md);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      onToast("Playground preview copied to clipboard");
    } catch {
      onToast("Failed to copy preview", "err");
    }
  }

  async function handleApplyAsReport() {
    if (!result?.preview_md) return;
    setApplying(true);
    try {
      await api.editDailyLog(day, result.preview_md);
      onToast(`Saved playground preview as daily report for ${day}`);
      onClose();
    } catch (err) {
      onToast(err instanceof Error ? err.message : String(err), "err");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200"
      role="dialog"
      aria-modal="true"
      aria-labelledby="playground-modal-title"
    >
      <div className="flex h-[90vh] max-h-[850px] w-full max-w-5xl flex-col rounded-2xl border border-white/10 bg-ink-900 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.08] px-5 py-3.5 bg-ink-950/40">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 text-amber-300 ring-1 ring-white/10">
              <SparkIcon className="h-4 w-4" />
            </div>
            <div>
              <h2 id="playground-modal-title" className="text-sm font-semibold text-ink-100">
                Report Playground
              </h2>
              <p className="text-[11px] text-ink-400">
                Test prompt customizations against telemetry without saving or overwriting daily digests (#349).
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close playground modal"
            className="rounded-lg p-1 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        {/* Content Body: Split layout */}
        <div className="grid flex-1 grid-cols-1 md:grid-cols-12 min-h-0 overflow-hidden">
          {/* Left Panel: Inputs & Knobs */}
          <div className="flex flex-col gap-3.5 border-r border-white/[0.08] p-4 md:col-span-5 overflow-y-auto bg-ink-950/20">
            {/* Day Selector */}
            <div>
              <label htmlFor="playground-day" className="block text-[11px] font-medium text-ink-300 mb-1">
                Target Day
              </label>
              <input
                id="playground-day"
                type="date"
                value={day}
                onChange={(e) => setDay(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-xs text-ink-100 focus:border-amber-400/50 focus:outline-none"
              />
              <span className="mt-1 block text-[10px] text-ink-500">
                Defaults to yesterday's recorded sessions and telemetry.
              </span>
            </div>

            {/* Prompt Override */}
            <div>
              <div className="mb-1 flex items-center justify-between">
                <label htmlFor="playground-prompt" className="text-[11px] font-medium text-ink-300">
                  Custom Prompt Override
                </label>
                {promptOverride && (
                  <button
                    onClick={() => setPromptOverride("")}
                    className="text-[10px] text-ink-500 hover:text-ink-300"
                  >
                    Clear
                  </button>
                )}
              </div>
              <textarea
                id="playground-prompt"
                value={promptOverride}
                onChange={(e) => setPromptOverride(e.target.value)}
                rows={4}
                placeholder="e.g. Highlight backend architectural improvements and ignore social media..."
                className="w-full rounded-lg border border-white/10 bg-white/[0.03] p-2 text-xs text-ink-100 placeholder:text-ink-600 focus:border-amber-400/50 focus:outline-none"
              />

              {/* Quick Presets */}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {PROMPT_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    onClick={() => setPromptOverride(preset.prompt)}
                    className="rounded-md border border-white/[0.06] bg-white/[0.02] px-2 py-0.5 text-[10px] text-ink-400 hover:border-amber-400/40 hover:text-ink-200 transition-colors"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Tone & Length */}
            <div className="grid grid-cols-2 gap-2.5">
              <div>
                <label htmlFor="playground-tone" className="block text-[11px] font-medium text-ink-300 mb-1">
                  Tone
                </label>
                <select
                  id="playground-tone"
                  value={tone}
                  onChange={(e) => setTone(e.target.value as any)}
                  className="w-full rounded-lg border border-white/10 bg-ink-900 px-2 py-1.5 text-xs text-ink-200 focus:border-amber-400/50 focus:outline-none"
                >
                  <option value="balanced">Balanced</option>
                  <option value="terse">Terse</option>
                  <option value="narrative">Narrative</option>
                  <option value="standup">Standup</option>
                </select>
              </div>

              <div>
                <label htmlFor="playground-length" className="block text-[11px] font-medium text-ink-300 mb-1">
                  Length
                </label>
                <select
                  id="playground-length"
                  value={length}
                  onChange={(e) => setLength(e.target.value as any)}
                  className="w-full rounded-lg border border-white/10 bg-ink-900 px-2 py-1.5 text-xs text-ink-200 focus:border-amber-400/50 focus:outline-none"
                >
                  <option value="short">Short</option>
                  <option value="medium">Medium</option>
                  <option value="long">Long</option>
                </select>
              </div>
            </div>

            {/* Toggles */}
            <div className="flex flex-col gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-ink-300">
                <input
                  type="checkbox"
                  checked={highlightsOnly}
                  onChange={(e) => setHighlightsOnly(e.target.checked)}
                  className="rounded border-white/20 bg-ink-950 text-amber-500 focus:ring-0"
                />
                <span>Highlights only (top accomplishments)</span>
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-ink-300">
                <input
                  type="checkbox"
                  checked={questionsForTomorrow}
                  onChange={(e) => setQuestionsForTomorrow(e.target.checked)}
                  className="rounded border-white/20 bg-ink-950 text-amber-500 focus:ring-0"
                />
                <span>Include questions for tomorrow</span>
              </label>
            </div>

            {/* Run Button */}
            <div className="mt-auto pt-2">
              <button
                onClick={handleRunTest}
                disabled={loading}
                className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 py-2 text-xs font-semibold text-white shadow-lg shadow-amber-500/10 transition-all hover:brightness-110 disabled:opacity-40"
              >
                {loading ? (
                  <>
                    <div className="h-3 w-3 animate-spin rounded-full border border-white border-t-transparent" />
                    <span>Synthesizing...</span>
                  </>
                ) : (
                  <>
                    <SparkIcon className="h-3.5 w-3.5" />
                    <span>Run Playground Test</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Right Panel: Output & Inspector */}
          <div className="flex flex-col md:col-span-7 min-h-0 bg-ink-950/40">
            {/* Tabs Header */}
            <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2 bg-ink-900/50">
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setActiveTab("preview")}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    activeTab === "preview"
                      ? "bg-white/[0.08] text-ink-100"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  Preview
                </button>
                <button
                  onClick={() => setActiveTab("prompt")}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    activeTab === "prompt"
                      ? "bg-white/[0.08] text-ink-100"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  System Prompt
                </button>
                <button
                  onClick={() => setActiveTab("transcript")}
                  className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    activeTab === "transcript"
                      ? "bg-white/[0.08] text-ink-100"
                      : "text-ink-400 hover:text-ink-200"
                  }`}
                >
                  Telemetry Transcript
                </button>
              </div>

              {result && (
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-ink-500">
                    {result.model === "fallback" ? "heuristics" : result.model}
                  </span>
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] text-ink-300 hover:bg-white/[0.04]"
                    title="Copy Markdown"
                  >
                    {copied ? <CheckIcon className="h-3 w-3 text-emerald-400" /> : <CopyIcon className="h-3 w-3" />}
                    <span>{copied ? "Copied" : "Copy"}</span>
                  </button>
                  <button
                    onClick={handleApplyAsReport}
                    disabled={applying}
                    className="flex items-center gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-40"
                    title="Save this preview as the stored daily report"
                  >
                    <span>Apply as Report</span>
                  </button>
                </div>
              )}
            </div>

            {/* Tab Panels */}
            <div className="flex-1 overflow-y-auto p-4 text-xs">
              {!result && !loading && (
                <div className="flex h-full flex-col items-center justify-center text-center py-12 text-ink-500">
                  <BotIcon className="h-8 w-8 text-ink-600 mb-2" />
                  <p className="max-w-xs text-xs">
                    Choose a day and prompt settings on the left, then click <strong>Run Playground Test</strong> to preview the results without altering your saved records.
                  </p>
                </div>
              )}

              {loading && (
                <div className="flex h-full flex-col items-center justify-center text-center py-12 text-ink-400">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-amber-400 border-t-transparent mb-3" />
                  <p className="text-xs">Synthesizing digest from local telemetry...</p>
                </div>
              )}

              {result && !loading && (
                <>
                  {activeTab === "preview" && (
                    <div
                      className="markdown-body leading-relaxed text-ink-200"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(result.preview_md) }}
                    />
                  )}

                  {activeTab === "prompt" && (
                    <div className="flex flex-col gap-2">
                      <span className="text-[10px] text-ink-500">
                        Exact system prompt dispatched to the LLM backend:
                      </span>
                      <pre className="whitespace-pre-wrap rounded-xl border border-white/[0.06] bg-black/40 p-3 font-mono text-[11px] text-ink-300 leading-relaxed">
                        {result.system_prompt}
                      </pre>
                    </div>
                  )}

                  {activeTab === "transcript" && (
                    <div className="flex flex-col gap-2">
                      <span className="text-[10px] text-ink-500">
                        Synthesized window activity, files, and git commits context:
                      </span>
                      <pre className="whitespace-pre-wrap rounded-xl border border-white/[0.06] bg-black/40 p-3 font-mono text-[11px] text-ink-300 leading-relaxed">
                        {result.transcript}
                      </pre>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
