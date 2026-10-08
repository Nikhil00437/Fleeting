/**
 * #58 context switches, #62 today vs the 7-day average.
 *
 * Both numbers are read from the backend so there is one definition of a
 * "switch"; this only renders them and says which way is better.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type { SwitchMetrics, TodayVsAverage } from "../types";

function fmtSecs(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${String(m).padStart(2, "0")}m` : `${h}h`;
}

export default function FocusMetrics({ day }: { day: string }) {
  const [switches, setSwitches] = useState<SwitchMetrics | null>(null);
  const [compare, setCompare] = useState<TodayVsAverage | null>(null);

  useEffect(() => {
    api.activitySwitches(day).then(setSwitches).catch(() => setSwitches(null));
    api.activityCompare(day).then(setCompare).catch(() => setCompare(null));
  }, [day]);

  if (!switches && !compare) return null;

  const delta = compare?.delta_seconds ?? 0;
  const tone = delta > 0 ? "text-emerald-300" : delta < 0 ? "text-ink-400" : "text-ink-400";

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
      {switches && (
        <span className="text-[11px] text-ink-400">
          Context switches{" "}
          <strong className="font-mono text-iris-300">{switches.switches}</strong>
          {switches.seconds_per_switch !== null && (
            <span className="text-ink-500">
              {" "}
              · {fmtSecs(switches.seconds_per_switch)} each
            </span>
          )}
        </span>
      )}
      {compare && (
        <span className="text-[11px] text-ink-400" title={`vs the previous ${compare.window} days`}>
          Today <strong className="font-mono text-ink-100">{fmtSecs(compare.seconds)}</strong>{" "}
          <span className={tone}>
            {delta >= 0 ? "+" : "−"}
            {fmtSecs(Math.abs(delta))}
          </span>{" "}
          <span className="text-ink-500">vs {compare.window}-day avg</span>
        </span>
      )}
    </div>
  );
}