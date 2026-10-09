/**
 * #112/#453 — formatting for the assistant's retrieval trace.
 *
 * Pure on purpose: the trace panel is the part of the assistant UI most likely
 * to be wrong quietly, and logic inside a `useEffect` cannot be asserted with
 * the SSR renderer.
 */

import type { LlmTrace } from "../types";

export interface ContextUsed {
  notes_count: number;
  tasks_count: number;
  logs_count: number;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? `1 ${one}` : `${n} ${many}`;
}

/** "5 notes, 3 tasks, no logs" — never "0 logs", which reads like a bug. */
export function summarizeContext(used: ContextUsed): string {
  const { notes_count: n, tasks_count: t, logs_count: l } = used;
  if (!n && !t && !l) return "nothing retrieved";
  return [
    n ? plural(n, "note") : "no notes",
    t ? plural(t, "task") : "no tasks",
    l ? plural(l, "log") : "no logs",
  ].join(", ");
}

/** One-line summary of a recorded LLM call. */
export function describeTrace(trace: LlmTrace): string {
  return `${plural(trace.queries.length, "search", "searches")}, ${
    trace.tool_calls.length ? plural(trace.tool_calls.length, "action") : "no actions"
  }, ${trace.ms}ms`;
}
