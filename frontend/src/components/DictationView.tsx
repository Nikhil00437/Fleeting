import { MicIcon, RefreshIcon } from "./Icons";
import { api } from "../api";
import { relTime } from "../time";
import type { Note } from "../types";

/**
 * #431: dictation history — every voice capture with the two actions you
 * actually want on a memo: paste it again, or re-run transcription.
 */
export default function DictationView({ notes, onToast }: { notes: Note[]; onToast?: (m: string, k?: "ok" | "err") => void }) {
  const memos = notes
    .filter((n) => n.type === "voice")
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));

  const desktop = typeof window !== "undefined" ? window.fleetingDesktop : undefined;

  async function reinsert(n: Note) {
    const text = (n.raw_text || "").trim();
    if (!text) return onToast?.("nothing to insert", "err");
    if (desktop?.typeText) {
      const ok = await desktop.typeText(text);
      onToast?.(ok ? "inserted at cursor" : "insertion failed — copied instead");
    } else {
      try {
        await navigator.clipboard.writeText(text);
        onToast?.("copied (desktop bridge unavailable)");
      } catch {
        onToast?.("no way to insert — clipboard blocked", "err");
      }
    }
  }

  async function retranscribe(n: Note) {
    try {
      await api.reprocess(n.id);
      onToast?.("re-transcribing…");
    } catch (e) {
      onToast?.(e instanceof Error ? e.message : String(e), "err");
    }
  }

  if (memos.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <div className="glass-studio flex h-14 w-14 items-center justify-center rounded-2xl">
          <MicIcon className="h-6 w-6 text-ember-400" />
        </div>
        <h2 className="mt-4 text-base font-semibold text-ink-100">No dictations yet</h2>
        <p className="mt-1 max-w-sm text-xs text-ink-400">
          Start a voice capture from the capture bar or the dictation HUD and it will land here.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-2 p-4">
      <h1 className="text-lg font-bold text-ink-100">Dictation history</h1>
      {memos.map((n) => {
        const lang = n.source?.transcription?.language;
        return (
          <div key={n.id} className="glass-studio flex items-start justify-between gap-3 rounded-xl p-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[11px] text-ink-400">
                <span>{relTime(n.created_at)}</span>
                {lang && <span className="rounded bg-iris-500/15 px-1 font-mono uppercase text-iris-300">{lang}</span>}
                <span className={`rounded px-1 ${n.status === "done" ? "text-emerald-400" : n.status === "failed" ? "text-red-300" : "text-ember-300"}`}>{n.status}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-ink-200">{n.raw_text || n.summary || "(no transcript)"}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button onClick={() => void reinsert(n)} className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:border-ember-400/40">
                Insert
              </button>
              <button onClick={() => void retranscribe(n)} title="Re-run transcription" className="rounded-lg p-1.5 text-ink-400 hover:text-ember-300">
                <RefreshIcon className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
