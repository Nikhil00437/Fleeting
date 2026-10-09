import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { ActivityIcon, BotIcon, CopyIcon, EditIcon, ExportIcon, FolderIcon, LinkIcon, SettingsIcon, SparkIcon } from "./Icons";
import WeeklyDigestCard from "./WeeklyDigestCard";
import OrphansCard from "./OrphansCard";
import UnfinishedThreadsCard from "./UnfinishedThreadsCard";
import CaptureFrequencyCard from "./CaptureFrequencyCard";
import EstimateAccuracyCard from "./EstimateAccuracyCard";
import FocusScoreCard from "./FocusScoreCard";
import TaskFunnelCard from "./TaskFunnelCard";
import BurndownChartCard from "./BurndownChartCard";
import RadialDayClock from "./RadialDayClock";
import ProjectTreemapCard from "./ProjectTreemapCard";
import StandupModal from "./StandupModal";
import PeriodicReviewModal from "./PeriodicReviewModal";
import ReportPlaygroundModal from "./ReportPlaygroundModal";
import WhatShippedModal from "./WhatShippedModal";
import { ProjectDashboardModal } from "./ProjectDashboardModal";
import ReportComparison from "./ReportComparison";
import type { Note } from "../types";

interface Props {
  onToast: (message: string, kind?: "ok" | "err") => void;
  /** Bumped when a report lands elsewhere, so this page stays in step. */
  refreshKey: number;
}

function todayLocal(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function shiftDay(day: string, delta: number): string {
  const d = new Date(`${day}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function prettyDay(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  const today = todayLocal();
  if (day === today) return "today";
  const yst = shiftDay(today, -1);
  if (day === yst) return "yesterday";
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

/** Strip our own heading so it is not repeated inside the card. */
function cleanDigestMarkdown(md: string): string {
  return md.replace(/^#?\s*Daily Digest\s*[\u2014-].*\n+/i, "").trim();
}

/**
 * Reports: the generated summaries, with nothing else on the page.
 *
 * These were the last two cards on the Timeline, which by then mixed a
 * day-scoped dashboard with two long-form reports and read as cramped. Reports
 * have their own rhythm (generate, read, step through time) so they get their
 * own page.
 */
export default function ReportsView({ onToast, refreshKey }: Props) {
  const [day, setDay] = useState(todayLocal());
  const [log, setLog] = useState<Awaited<ReturnType<typeof api.dailyLog>> | null>(null);
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [saving, setSaving] = useState(false);
  const [evidenceMode, setEvidenceMode] = useState(false);

  const [showOptions, setShowOptions] = useState(false);
  const [tone, setTone] = useState<"balanced" | "terse" | "narrative" | "standup">("balanced");
  const [length, setLength] = useState<"short" | "medium" | "long">("medium");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [highlightsOnly, setHighlightsOnly] = useState(false);
  const [questionsForTomorrow, setQuestionsForTomorrow] = useState(false);
  const [promptOverride, setPromptOverride] = useState("");

  const [reflectionPrompts, setReflectionPrompts] = useState<string[]>([]);
  const [promptIdx, setPromptIdx] = useState(0);
  const [reflectionText, setReflectionText] = useState("");
  const [reflectionNote, setReflectionNote] = useState<Note | null>(null);
  const [savingReflection, setSavingReflection] = useState(false);
  const [showStandup, setShowStandup] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [showPlayground, setShowPlayground] = useState(false);
  const [showWhatShipped, setShowWhatShipped] = useState(false);
  const [showProjects, setShowProjects] = useState(false);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compareDay, setCompareDay] = useState(() => shiftDay(todayLocal(), -1));

  const isToday = day === todayLocal();

  const load = useCallback(() => {
    api.dailyLog(day).then((data) => {
      setLog(data);
      setEditing(false);
    }).catch(() => {});
    api.dailyReflection(day).then((ref) => {
      setReflectionPrompts(ref.prompts || []);
      setReflectionNote(ref.note);
      setPromptIdx(0);
      setReflectionText("");
    }).catch(() => {});
  }, [day]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function generate() {
    setGenerating(true);
    try {
      const opts = {
        tone,
        length,
        start_time: startTime.trim() || undefined,
        end_time: endTime.trim() || undefined,
        highlights_only: highlightsOnly,
        questions_for_tomorrow: questionsForTomorrow,
        prompt_override: promptOverride.trim() || undefined,
      };
      const updated = await api.generateDailyLog(day, isToday, opts);
      setLog(updated);
      setEditing(false);
      if (updated.edited) {
        onToast("daily report regenerated (kept your edits)");
      } else {
        onToast("daily report updated");
      }
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setGenerating(false);
    }
  }

  async function handleSave() {
    if (!log) return;
    setSaving(true);
    try {
      await api.editDailyLog(day, editText);
      const isTrimmed = Boolean(editText.trim());
      setLog({
        ...log,
        edited: isTrimmed ? 1 : 0,
        edited_body: isTrimmed ? editText : null,
      });
      setEditing(false);
      onToast(isTrimmed ? "report edits saved" : "cleared edits");
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setSaving(false);
    }
  }

  async function handleRevert() {
    if (!log) return;
    setSaving(true);
    try {
      await api.clearDailyLogEdit(day);
      setLog({ ...log, edited: 0, edited_body: null });
      setEditText(log.summary_md || "");
      setEditing(false);
      onToast("reverted to original AI summary");
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveReflection() {
    if (!reflectionText.trim()) return;
    setSavingReflection(true);
    const activePrompt = reflectionPrompts[promptIdx] || "Daily Reflection";
    try {
      const created = await api.saveDailyReflection(day, activePrompt, reflectionText.trim());
      setReflectionNote(created);
      onToast("reflection saved as linked note");
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setSavingReflection(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3.5 overflow-y-auto p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-sm font-semibold text-ink-100">Reports</h1>
          <p className="text-[11px] text-ink-400">
            Daily and weekly summaries written by your local model.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setDay((d) => shiftDay(d, -1))}
            aria-label="Previous day"
            className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40"
          >
            \u2039
          </button>
          <span className="min-w-32 text-center font-mono text-xs text-ink-200">
            {prettyDay(day)}
          </span>
          <button
            onClick={() => setDay((d) => shiftDay(d, 1))}
            disabled={isToday}
            aria-label="Next day"
            className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
          >
            \u203a
          </button>
          {!isToday && (
            <button
              onClick={() => setDay(todayLocal())}
              className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-ink-400 hover:border-ember-400/40"
            >
              Today
            </button>
          )}
          <button
            onClick={() => setShowStandup(true)}
            data-testid="open-standup-button"
            className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:border-ember-400/40"
            title="Generate daily standup: yesterday, today, blockers"
          >
            <SparkIcon className="h-3.5 w-3.5 text-amber-400" />
            Standup
          </button>
          <button
            onClick={() => setShowReview(true)}
            data-testid="open-review-button"
            className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:border-ember-400/40"
            title="Periodic reviews: Monthly, Quarterly, and Year in Review (Wrapped)"
          >
            <ActivityIcon className="h-3.5 w-3.5 text-purple-400" />
            Review
          </button>
          <button
            onClick={() => setShowPlayground(true)}
            data-testid="open-playground-button"
            className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:border-ember-400/40"
            title="Test prompt customizations against telemetry in a sandbox (#349)"
          >
            <BotIcon className="h-3.5 w-3.5 text-amber-400" />
            Playground
          </button>
          <button
            onClick={() => setShowWhatShipped(true)}
            data-testid="open-what-shipped-button"
            className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:border-emerald-400/40"
            title="Weekly changelog combining commits, completed tasks, and notes (#166)"
          >
            <SparkIcon className="h-3.5 w-3.5 text-emerald-400" />
            What Shipped
          </button>
          <button
            onClick={() => setShowProjects(true)}
            data-testid="open-projects-button"
            className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:border-ember-400/40"
            title="Per-project dashboards with telemetry, commits, tasks and notes (#167)"
          >
            <FolderIcon className="h-3.5 w-3.5 text-ember-400" />
            Projects
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-2">
    <div className="xl:col-span-2">
      <WeeklyDigestCard onToast={onToast} refreshKey={refreshKey} />
    </div>

    {/* #422 housekeeping */}
    <div className="xl:col-span-2">
      <OrphansCard onToast={onToast} refreshKey={refreshKey} />
    </div>

    {/* #169 persistent unfinished threads */}
    <div className="xl:col-span-2">
      <UnfinishedThreadsCard onToast={onToast} refreshKey={refreshKey} />
    </div>

    {/* #163 capture frequency & tag trends */}
    <div className="xl:col-span-2">
      <CaptureFrequencyCard onToast={onToast} refreshKey={refreshKey} />
    </div>

    {/* #170 time-estimate accuracy */}
    <div className="xl:col-span-2">
      <EstimateAccuracyCard refreshKey={refreshKey} />
    </div>

    {/* #57 daily focus score trend */}
    <div className="xl:col-span-2">
      <FocusScoreCard refreshKey={refreshKey} onSelectDay={setDay} />
    </div>

    {/* #250 task conversion funnel */}
    <div className="xl:col-span-2">
      <TaskFunnelCard refreshKey={refreshKey} />
    </div>

    {/* #423 backlog burndown chart */}
    <div className="xl:col-span-2">
      <BurndownChartCard refreshKey={refreshKey} />
    </div>

    {/* #247 24-hour radial day clock */}
    <div className="xl:col-span-2">
      <RadialDayClock refreshKey={refreshKey} initialDay={day} onSelectDay={setDay} />
    </div>

    {/* #251 project time treemap */}
    <div className="xl:col-span-2">
      <ProjectTreemapCard
        refreshKey={refreshKey}
        onSelectProject={(proj) => {
          setSelectedProject(proj);
          setShowProjects(true);
        }}
      />
    </div>

    {/* Daily AI Report or Side-by-Side Comparison (#71) */}
    <div className="xl:col-span-2">
      {compareMode ? (
        <ReportComparison
          dayA={day}
          dayB={compareDay}
          onDayAChange={setDay}
          onDayBChange={setCompareDay}
          onClose={() => setCompareMode(false)}
          onToast={onToast}
          refreshKey={refreshKey}
        />
      ) : (
        <div className="glass-studio glow-border flex h-full flex-col rounded-2xl p-4">
        <div className="mb-3 flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-iris-500/25 to-ember-500/20 text-iris-300 ring-1 ring-white/10">
            <BotIcon className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold text-ink-100">Daily AI Executive Digest</p>
              {Boolean(log?.edited) && (
                <span
                  className="rounded bg-iris-500/15 px-1.5 py-0.5 text-[10px] font-medium text-iris-300 ring-1 ring-iris-500/30"
                  title="Human-edited; kept across regenerations"
                >
                  Edited
                </span>
              )}
            </div>
            <p className="truncate font-mono text-[10px] text-ink-400">
              {log?.model === "fallback"
                ? "offline heuristics"
                : log?.model
                  ? log.model
                  : "local LLM"}
              {" · "}
              {isToday ? "rolling 24h" : prettyDay(day)}
            </p>
          </div>
          {log?.summary_md && (
            <>
              <button
                onClick={() => {
                  if (editing) {
                    setEditing(false);
                  } else {
                    setEditText(log.edited_body ?? log.summary_md ?? "");
                    setEditing(true);
                  }
                }}
                className={`rounded-lg border p-1.5 transition-colors ${
                  editing
                    ? "border-ember-400/50 bg-ember-500/10 text-ember-300"
                    : "border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/20 hover:text-ink-100"
                }`}
                title={editing ? "Cancel edit" : "Edit report"}
                aria-label={editing ? "Cancel edit" : "Edit report"}
              >
                <EditIcon className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={async () => {
                  await navigator.clipboard.writeText(log.edited_body ?? log.summary_md!);
                  onToast("report markdown copied");
                }}
                className="rounded-lg border border-white/10 bg-white/[0.03] p-1.5 text-ink-300 transition-colors hover:border-white/20 hover:text-ink-100"
                title="Copy report markdown"
              >
                <CopyIcon className="h-3.5 w-3.5" />
              </button>
              {Boolean(log.evidence && log.evidence.length > 0) && (
                <button
                  onClick={() => setEvidenceMode(!evidenceMode)}
                  className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors ${
                    evidenceMode
                      ? "border-iris-400/50 bg-iris-500/15 text-iris-300 ring-1 ring-iris-500/30"
                      : "border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/20 hover:text-ink-100"
                  }`}
                  title="Evidence mode: expand sentences and sections to their source telemetry (#73, #350)"
                  aria-label="Toggle evidence mode"
                >
                  <LinkIcon className="h-3 w-3" />
                  <span className="hidden sm:inline">Evidence</span>
                </button>
              )}
              <a
                href={api.exportDailyLogUrl(day, "md")}
                download={`daily-log-${day}.md`}
                className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-xs text-ink-300 transition-colors hover:border-white/20 hover:text-ink-100"
                title="Export report as Markdown (#74)"
                aria-label="Export Markdown"
              >
                <ExportIcon className="h-3 w-3" />
                <span className="hidden sm:inline">MD</span>
              </a>
              <a
                href={api.exportDailyLogUrl(day, "pdf")}
                download={`daily-log-${day}.pdf`}
                className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1 text-xs text-ink-300 transition-colors hover:border-white/20 hover:text-ink-100"
                title="Export report as PDF (#74)"
                aria-label="Export PDF"
              >
                <ExportIcon className="h-3 w-3" />
                <span className="hidden sm:inline">PDF</span>
              </a>
            </>
          )}
          <button
            onClick={() => setShowOptions(!showOptions)}
            className={`flex items-center gap-1 rounded-lg border px-2 py-1.5 text-xs transition-colors ${
              showOptions
                ? "border-ember-400/50 bg-ember-500/10 text-ember-300 ring-1 ring-ember-500/30"
                : "border-white/10 bg-white/[0.03] text-ink-300 hover:border-white/20 hover:text-ink-100"
            }`}
            title="Configure report tone, length, window, and sections"
            aria-label="Report options"
          >
            <SettingsIcon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Options</span>
          </button>
          <button
            onClick={() => setCompareMode(true)}
            data-testid="toggle-compare-button"
            className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-2 py-1.5 text-xs text-ink-300 transition-colors hover:border-white/20 hover:text-ink-100"
            title="Compare with another day's report side-by-side (#71)"
            aria-label="Compare side-by-side"
          >
            <span className="hidden sm:inline">Compare</span>
          </button>
          <button
            onClick={() => void generate()}
            disabled={generating}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-br from-ember-400 to-ember-600 px-3 py-1.5 text-xs font-semibold text-ink-950 shadow-sm transition-all hover:brightness-110 disabled:opacity-60"
          >
            {generating ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-950/30 border-t-ink-950" />
            ) : (
              <BotIcon className="h-3.5 w-3.5" />
            )}
            {log?.summary_md ? "Regen" : "Generate"}
          </button>
        </div>

        {showOptions && (
          <div className="mb-3 flex flex-col gap-2.5 rounded-xl border border-white/10 bg-ink-950/40 p-3 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* Tone */}
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] text-ink-400">Tone:</span>
                {(["balanced", "terse", "narrative", "standup"] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTone(t)}
                    className={`rounded px-2 py-0.5 text-[11px] capitalize transition-colors ${
                      tone === t
                        ? "bg-ember-500/20 text-ember-300 ring-1 ring-ember-500/40"
                        : "bg-white/[0.04] text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>

              {/* Length */}
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] text-ink-400">Length:</span>
                {(["short", "medium", "long"] as const).map((l) => (
                  <button
                    key={l}
                    onClick={() => setLength(l)}
                    className={`rounded px-2 py-0.5 text-[11px] capitalize transition-colors ${
                      length === l
                        ? "bg-iris-500/20 text-iris-300 ring-1 ring-iris-500/40"
                        : "bg-white/[0.04] text-ink-400 hover:text-ink-200"
                    }`}
                  >
                    {l}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-4 text-[11px] text-ink-300">
              {/* Window */}
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[10px] text-ink-400">Window:</span>
                <input
                  type="time"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  placeholder="09:00"
                  className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-ink-200 focus:border-ember-400/50 focus:outline-none"
                  aria-label="Window start time"
                />
                <span className="text-ink-500">–</span>
                <input
                  type="time"
                  value={endTime}
                  onChange={(e) => setEndTime(e.target.value)}
                  placeholder="18:00"
                  className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-ink-200 focus:border-ember-400/50 focus:outline-none"
                  aria-label="Window end time"
                />
              </div>

              {/* Checkboxes */}
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={highlightsOnly}
                  onChange={(e) => setHighlightsOnly(e.target.checked)}
                  className="rounded border-white/20 bg-white/[0.04] text-ember-500 focus:ring-0"
                />
                <span>Highlights only</span>
              </label>

              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={questionsForTomorrow}
                  onChange={(e) => setQuestionsForTomorrow(e.target.checked)}
                  className="rounded border-white/20 bg-white/[0.04] text-ember-500 focus:ring-0"
                />
                <span>Questions for tomorrow</span>
              </label>
            </div>

            {/* Prompt override */}
            <div className="flex items-center gap-2">
              <span className="font-mono text-[10px] text-ink-400 shrink-0">Custom instructions:</span>
              <input
                type="text"
                value={promptOverride}
                onChange={(e) => setPromptOverride(e.target.value)}
                placeholder="e.g. Focus deeply on PR reviews and frontend architecture..."
                className="flex-1 rounded border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[11px] text-ink-200 placeholder:text-ink-500 focus:border-ember-400/50 focus:outline-none"
                aria-label="Custom instructions"
              />
            </div>
          </div>
        )}

        {generating && (
          <div className="space-y-2.5 py-4">
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="shimmer h-3.5 rounded"
                style={{ width: `${92 - i * 12}%` }}
              />
            ))}
          </div>
        )}

        {!generating && editing && (
          <div className="flex flex-1 flex-col gap-2 min-h-0">
            <div className="flex items-center justify-between text-[11px] text-ink-400">
              <span>Editing report markdown — edits are kept when regenerating.</span>
              {Boolean(log?.edited) && (
                <button
                  onClick={handleRevert}
                  disabled={saving}
                  className="text-[11px] text-ember-400 underline hover:text-ember-300 disabled:opacity-50"
                >
                  Revert to AI version
                </button>
              )}
            </div>
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              disabled={saving}
              className="w-full flex-1 min-h-[160px] max-h-96 rounded-xl border border-ink-700 bg-ink-950/80 p-3 font-mono text-xs text-ink-100 placeholder-ink-500 focus:border-ember-400 focus:outline-none"
              placeholder="Write your digest..."
            />
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={() => setEditing(false)}
                disabled={saving}
                className="rounded-lg border border-ink-700 bg-ink-900 px-3 py-1.5 text-xs text-ink-300 hover:border-ink-600 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="rounded-lg bg-gradient-to-br from-ember-400 to-ember-600 px-3 py-1.5 text-xs font-semibold text-ink-950 hover:brightness-110 disabled:opacity-60"
              >
                {saving ? "Saving..." : "Save edits"}
              </button>
            </div>
          </div>
        )}

        {!generating && !editing && log?.summary_md && (
          <div
            className="md selectable max-h-60 min-h-0 flex-1 overflow-y-auto pr-1 text-xs"
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(cleanDigestMarkdown(log.edited_body ?? log.summary_md)),
            }}
          />
        )}

        {!generating && !editing && evidenceMode && log?.evidence && log.evidence.length > 0 && (
          <div className="mt-3 rounded-xl border border-iris-500/20 bg-iris-950/20 p-3 text-xs" aria-label="Evidence Explorer">
            <div className="mb-2 flex items-center justify-between border-b border-iris-500/15 pb-2">
              <span className="font-semibold text-iris-200">
                Evidence Mode — Source telemetry & notes (#73, #350)
              </span>
              <span className="font-mono text-[10px] text-iris-400">
                {log.evidence.length} citations
              </span>
            </div>

            <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
              {log.evidence.map((item, idx) => {
                const isHeader = item.text === item.section;
                const totalSources = (item.sessions?.length || 0) + (item.notes?.length || 0) + (item.commits?.length || 0);
                if (totalSources === 0) return null;

                return (
                  <div
                    key={idx}
                    className={`rounded-lg p-2.5 ${
                      isHeader
                        ? "border border-white/[0.08] bg-white/[0.03]"
                        : "ml-2 border border-ink-800 bg-ink-900/60"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className={`text-xs ${isHeader ? "font-semibold text-ink-100" : "text-ink-200 italic"}`}>
                        {isHeader ? `§ ${item.section}` : `“${item.text}”`}
                      </p>
                      <span className="shrink-0 rounded bg-ink-800 px-1.5 py-0.5 text-[10px] font-mono text-ink-400">
                        {totalSources} {totalSources === 1 ? "source" : "sources"}
                      </span>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {item.sessions?.map((s, si) => (
                        <div
                          key={`s-${si}`}
                          className="flex items-center gap-1 rounded border border-iris-500/25 bg-iris-500/10 px-2 py-0.5 text-[10px] text-iris-300"
                          title={`${s.app}: ${s.title} (${Math.round(s.seconds / 60)}m)`}
                        >
                          <span className="font-medium">{s.app}</span>
                          {s.start && <span className="font-mono text-[9px] text-iris-400">[{s.start}–{s.end}]</span>}
                          <span className="text-iris-400">({Math.round(s.seconds / 60)}m)</span>
                          {s.title && <span className="max-w-44 truncate text-ink-400">· {s.title}</span>}
                        </div>
                      ))}

                      {item.notes?.map((n, ni) => (
                        <div
                          key={`n-${ni}`}
                          className="flex items-center gap-1 rounded border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300"
                          title={`Linked note: ${n.title}`}
                        >
                          <span className="font-medium">Note:</span>
                          <span className="max-w-52 truncate">{n.title}</span>
                        </div>
                      ))}

                      {item.commits?.map((c, ci) => (
                        <div
                          key={`c-${ci}`}
                          className="flex items-center gap-1 rounded border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300"
                          title={`${c.repo}: ${c.subject}`}
                        >
                          <span className="font-medium">{c.repo}:</span>
                          <span className="max-w-52 truncate">{c.subject}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* #347 Daily Reflection Journaling */}
        {!generating && !editing && log?.summary_md && (
          <div className="mt-3 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3 text-xs" aria-label="Daily Reflection">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5 font-semibold text-ink-200">
                <SparkIcon className="h-3.5 w-3.5 text-ember-400" />
                <span>Daily Reflection</span>
              </div>
              {reflectionNote && (
                <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-medium text-emerald-300 ring-1 ring-emerald-500/30">
                  Linked Note Saved
                </span>
              )}
            </div>

            {reflectionNote ? (
              <div className="rounded-lg border border-white/[0.06] bg-ink-950/40 p-2.5">
                <p className="font-medium text-ink-100">{reflectionNote.title}</p>
                <p className="mt-1 line-clamp-3 text-ink-300 whitespace-pre-wrap">{reflectionNote.raw_text}</p>
                <div className="mt-2 flex items-center gap-2 text-[10px] text-ink-400">
                  <span className="font-mono">Tags: {reflectionNote.tags?.join(", ")}</span>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-2 rounded-lg bg-ink-950/30 px-2.5 py-2">
                  <p className="text-ink-300 italic">“{reflectionPrompts[promptIdx] || "What gave you momentum today, and what drained your focus?"}”</p>
                  {reflectionPrompts.length > 1 && (
                    <button
                      onClick={() => setPromptIdx((idx) => (idx + 1) % reflectionPrompts.length)}
                      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-ink-400 hover:text-ink-200"
                      title="Next reflection prompt"
                    >
                      Shuffle
                    </button>
                  )}
                </div>
                <textarea
                  value={reflectionText}
                  onChange={(e) => setReflectionText(e.target.value)}
                  placeholder="Jot down your reflection for today..."
                  rows={3}
                  className="w-full rounded-lg border border-white/10 bg-white/[0.04] p-2 text-xs text-ink-100 placeholder:text-ink-500 focus:border-ember-400/50 focus:outline-none"
                  aria-label="Reflection response"
                />
                <div className="flex justify-end">
                  <button
                    onClick={handleSaveReflection}
                    disabled={savingReflection || !reflectionText.trim()}
                    className="flex items-center gap-1 rounded-lg bg-ember-500/20 px-3 py-1 text-xs font-medium text-ember-300 transition-colors hover:bg-ember-500/30 disabled:opacity-40"
                  >
                    Save Reflection as Note
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {!generating && !log?.summary_md && (
          <div className="flex flex-1 flex-col items-center justify-center py-6 text-center">
            <ActivityIcon className="h-6 w-6 text-ink-600" />
            <p className="mt-2 max-w-xs text-xs leading-relaxed text-ink-400">
              Synthesizes window sessions, modified files, and git commits into a daily
              briefing automatically every 1h of screentime and at midnight — or click
              Generate anytime.
            </p>
          </div>
        )}
      </div>
      )}
    </div>
      </div>

      {showStandup && (
        <StandupModal
          isOpen={showStandup}
          onClose={() => setShowStandup(false)}
          onToast={onToast}
          day={day}
        />
      )}

      {showReview && (
        <PeriodicReviewModal
          isOpen={showReview}
          onClose={() => setShowReview(false)}
          onToast={onToast}
        />
      )}

      {showPlayground && (
        <ReportPlaygroundModal
          isOpen={showPlayground}
          onClose={() => setShowPlayground(false)}
          onToast={onToast}
          initialDay={shiftDay(todayLocal(), -1)}
        />
      )}

      {showWhatShipped && (
        <WhatShippedModal
          isOpen={showWhatShipped}
          onClose={() => setShowWhatShipped(false)}
          onToast={onToast}
        />
      )}

      {showProjects && (
        <ProjectDashboardModal
          initialProject={selectedProject}
          onClose={() => {
            setShowProjects(false);
            setSelectedProject(null);
          }}
        />
      )}
    </div>
  );
}
