import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fmtSecs } from "../apps";
import { renderMarkdown } from "../markdown";
import { BotIcon, RefreshIcon } from "./Icons";
import { weekLabel, weekProgress } from "./weekly";
import type { WeeklyLogOut } from "../types";

/** Strip our own title so the card does not repeat the heading inside it. */
function cleanWeeklyMarkdown(md: string): string {
  return md.replace(/^#\s*Weekly Digest\s*[—-].*\n+/i, "").trim();
}

interface Props {
  onToast: (message: string, kind?: "ok" | "err") => void;
  /** Bumped when a daily report lands, so the week refreshes with it. */
  refreshKey: number;
}

/** Weekly AI digest: the shape of the finished week, not just Monday's 24h. */
export default function WeeklyDigestCard({ onToast, refreshKey }: Props) {
  const [data, setData] = useState<WeeklyLogOut | null>(null);
  const [week, setWeek] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    (target?: string) => {
      setLoading(true);
      api
        .weeklyLog(target)
        .then((d) => {
          setData(d);
          setWeek(d.week);
        })
        .catch((e) => onToast(e instanceof Error ? e.message : String(e), "err"))
        .finally(() => setLoading(false));
    },
    [onToast],
  );

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  async function generate() {
    if (!week) return;
    setBusy(true);
    try {
      await api.generateWeeklyLog(week);
      onToast("Weekly digest ready");
      load(week);
    } catch (e) {
      onToast(e instanceof Error ? e.message : String(e), "err");
    } finally {
      setBusy(false);
    }
  }

  function step(dir: -1 | 1) {
    if (!data) return;
    const d = new Date(`${data.week}T00:00:00`);
    if (Number.isNaN(d.getTime())) return;
    d.setDate(d.getDate() + dir * 7);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
    load(iso);
  }

  const progress = weekProgress(data?.summary?.days);
  const report = data?.report ?? null;
  const isCurrent = week === data?.this_week;

  return (
    <div className="glass-studio glow-border flex h-full flex-col rounded-2xl p-4">
      <div className="mb-3 flex items-center gap-2.5 border-b border-white/[0.06] pb-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/25 to-iris-500/20 text-emerald-300 ring-1 ring-white/10">
          <BotIcon className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-ink-100">Weekly Digest</p>
          <p className="truncate font-mono text-[10px] text-ink-400">
            {week ? weekLabel(week) : "loading…"}
            {" · "}
            {report?.model === "fallback"
              ? "offline heuristics"
              : report?.model
                ? report.model
                : "local LLM"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => step(-1)}
            aria-label="Previous week"
            className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 text-[11px] text-ink-300 hover:border-ember-400/40"
          >
            ‹
          </button>
          <button
            onClick={() => step(1)}
            disabled={isCurrent}
            aria-label="Next week"
            className="rounded-lg border border-ink-700 bg-ink-900 px-2 py-1 text-[11px] text-ink-300 hover:border-ember-400/40 disabled:opacity-40"
          >
            ›
          </button>
          <button
            onClick={() => void generate()}
            disabled={busy || loading}
            className="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] font-semibold text-ink-200 hover:border-ember-400/40 disabled:opacity-50"
          >
            <RefreshIcon className="h-3 w-3" />
            {busy ? "Writing…" : report ? "Regen" : "Generate"}
          </button>
        </div>
      </div>

      <div className="mb-3 grid grid-cols-4 gap-2 font-mono text-[11px]">
        <div>
          <p className="micro-label !text-[9px]">Focus</p>
          <p className="tabular-nums text-ink-100">{fmtSecs(progress.totalSeconds)}</p>
        </div>
        <div>
          <p className="micro-label !text-[9px]">Active days</p>
          <p className="tabular-nums text-ink-100">{progress.busyDays}/7</p>
        </div>
        <div>
          <p className="micro-label !text-[9px]">Daily avg</p>
          <p className="tabular-nums text-ink-100">{fmtSecs(progress.averageSeconds)}</p>
        </div>
        <div>
          <p className="micro-label !text-[9px]">Open tasks</p>
          <p className="tabular-nums text-ink-100">{data?.summary?.open_tasks ?? 0}</p>
        </div>
      </div>

      {(data?.diff?.narrative ?? data?.summary?.diff?.narrative) ? (
        <div
          data-testid="weekly-diff-callout"
          className="mb-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-2.5 text-xs text-ink-300"
        >
          <span className="font-semibold text-ink-100">vs. last week:</span>{" "}
          {data?.diff?.narrative ?? data?.summary?.diff?.narrative}
        </div>
      ) : null}

      {isCurrent ? (
        <p className="text-xs text-ink-400">
          This week is still in progress — switch back a week to read a finished one.
        </p>
      ) : !busy && report?.summary_md ? (
        <div
          className="digest-body min-h-0 flex-1 overflow-y-auto text-sm leading-relaxed text-ink-200"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(cleanWeeklyMarkdown(report.summary_md)) }}
        />
      ) : !busy && !report?.summary_md ? (
        <p className="text-xs text-ink-400">
          No weekly digest yet. Generate one to summarise the week from its window sessions,
          commits and captures.
        </p>
      ) : null}
    </div>
  );
}
