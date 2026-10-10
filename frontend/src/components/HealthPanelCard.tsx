/** #94 health panel: latency, queue depth, embedding status, one-click retry. */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { HealthPanel } from "../types";
import { describeHealth } from "./health";

function Pill({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div
      className={`rounded-lg border px-2.5 py-1.5 ${
        warn ? "border-amber-500/30 bg-amber-500/[0.07]" : "border-white/[0.05] bg-white/[0.02]"
      }`}
    >
      <p className="micro-label !text-[9px]">{label}</p>
      <p className={`font-mono text-[11px] ${warn ? "text-amber-300" : "text-ink-200"}`}>{value}</p>
    </div>
  );
}

export function HealthPanelCard() {
  const [panel, setPanel] = useState<HealthPanel | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .healthPanel()
      .then(setPanel)
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function retry() {
    setBusy(true);
    setNote(null);
    try {
      const res = await api.healthPanelRetry();
      setNote(res.ok ? `Reachable — ${res.models?.length ?? 0} chat models` : res.detail || "unreachable");
      load();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "probe failed");
    } finally {
      setBusy(false);
    }
  }

  if (!panel) {
    return <p className="text-xs text-ink-500">Reading health…</p>;
  }

  const { llm, embeddings, queue } = panel;
  const degraded = embeddings.degraded || llm.errors > 0 || queue.depth >= queue.max;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Pill
          label="LLM latency"
          value={llm.calls ? `${llm.avg_ms}ms avg` : "no calls yet"}
          warn={llm.errors > 0}
        />
        <Pill
          label="Failed calls"
          value={`${llm.errors} of last ${llm.calls}`}
          warn={llm.errors > 0}
        />
        <Pill
          label="Embeddings"
          value={embeddings.degraded ? "degraded" : embeddings.model || "not used yet"}
          warn={embeddings.degraded}
        />
        <Pill
          label="Capture queue"
          value={`${queue.depth}/${queue.max}${queue.inflight ? ` · ${queue.inflight} in flight` : ""}`}
          warn={queue.depth >= queue.max}
        />
      </div>

      <p className={`text-[11px] leading-relaxed ${degraded ? "text-amber-300" : "text-ink-400"}`}>
        {describeHealth(panel)}
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={retry}
          disabled={busy}
          className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 transition-colors hover:bg-ink-800 disabled:opacity-40 cursor-pointer"
          data-testid="health-retry"
        >
          {busy ? "Retrying…" : "Retry connection"}
        </button>
        {note && <span className="font-mono text-[10px] text-ink-400">{note}</span>}
      </div>
    </div>
  );
}
