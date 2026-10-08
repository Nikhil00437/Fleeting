import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { ActivityIcon, BotIcon, CopyIcon, EditIcon, LinkIcon, SettingsIcon } from "./Icons";
import WeeklyDigestCard from "./WeeklyDigestCard";
import OrphansCard from "./OrphansCard";

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

  const isToday = day === todayLocal();

  const load = useCallback(() => {
    api.dailyLog(day).then((data) => {
      setLog(data);
      setEditing(false);
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

    {/* Daily AI Report */}
    <div className="xl:col-span-2">
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
    </div>
      </div>
    </div>
  );
}
