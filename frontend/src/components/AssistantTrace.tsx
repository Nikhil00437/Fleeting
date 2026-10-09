/**
 * #112 tool-use transparency, #453 "what will the LLM see?".
 *
 * Both render the same underlying fact — the retrieval trace — so they share
 * the collapsed/expanded shell rather than each inventing a disclosure style.
 */
import { FolderIcon } from "./Icons";
import { describeTrace, summarizeContext } from "./assistantTrace";
import type { ContextPreview as Preview, LlmTrace } from "../types";

function Disclosure({
  label,
  detail,
  expanded,
  onToggle,
  testId,
}: {
  label: string;
  detail?: string;
  expanded: boolean;
  onToggle: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      data-testid={testId}
      className="flex w-full items-center gap-1.5 text-left font-mono text-[11px] text-ink-400 transition-colors hover:text-ink-200 cursor-pointer"
    >
      <FolderIcon className="h-3 w-3 shrink-0 text-ink-500" />
      <span className="font-medium">{label}</span>
      {detail && <span className="truncate text-ink-500 text-[10px]">{detail}</span>}
      <span className="ml-auto text-[10px]" aria-hidden="true">
        {expanded ? "▲" : "▼"}
      </span>
    </button>
  );
}

function CodeBlock({ text }: { text: string }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-white/[0.05] bg-ink-950/80 p-2.5 font-mono text-[10px] leading-relaxed text-ink-300 whitespace-pre-wrap">
      {text}
    </pre>
  );
}

export function AssistantTraceRow({
  trace,
  expanded,
  onToggle,
}: {
  trace: LlmTrace;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="rounded-xl border border-white/[0.05] bg-ink-950/40 p-2.5">
      <Disclosure
        label="Trace"
        detail={describeTrace(trace)}
        expanded={expanded}
        onToggle={onToggle}
        testId={`trace-toggle-${trace.id}`}
      />
      {expanded && (
        <div className="mt-2 space-y-2">
          {/* The typed question is often not the query that found the answer —
              retrieval degrades through phrase → keyword phrase → single
              keyword, so showing only the first would be a lie. */}
          <div>
            <p className="micro-label">Searches run</p>
            <ul className="mt-1 space-y-0.5">
              {trace.queries.map((q, i) => (
                <li key={`${trace.id}-q${i}`} className="font-mono text-[10px] text-ink-300">
                  {q}
                </li>
              ))}
            </ul>
          </div>
          {trace.tool_calls.length > 0 && (
            <div>
              <p className="micro-label">Actions</p>
              <ul className="mt-1 space-y-0.5">
                {trace.tool_calls.map((c, i) => (
                  <li key={`${trace.id}-t${i}`} className="font-mono text-[10px] text-ember-300">
                    {c.tool}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="micro-label">Context sent</p>
            <div className="mt-1">
              <CodeBlock text={trace.context || "(empty)"} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ContextPreview({
  preview,
  onClose,
}: {
  preview: Preview;
  onClose: () => void;
}) {
  const empty = !preview.context;
  return (
    <div className="space-y-2 rounded-xl border border-ember-500/20 bg-ink-950/60 p-3">
      <div className="flex items-center gap-2">
        <p className="text-[11px] font-semibold text-ink-200">What the model will see</p>
        <span className="font-mono text-[10px] text-ink-500">
          · {summarizeContext(preview.context_used)}
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close context preview"
          className="ml-auto font-mono text-[10px] text-ink-500 hover:text-ink-200 cursor-pointer"
        >
          close
        </button>
      </div>

      {empty ? (
        <p className="font-mono text-[10px] text-ink-500">
          Nothing retrieved — this question would be sent with no context at all.
        </p>
      ) : (
        <>
          <ul className="flex flex-wrap gap-1">
            {preview.sources.map((s) => (
              <li
                key={`${s.kind}-${s.id}`}
                className="rounded-md border border-white/[0.05] bg-white/[0.03] px-1.5 py-0.5 text-[10px] text-ink-300"
              >
                {s.title}
              </li>
            ))}
          </ul>
          <CodeBlock text={preview.context} />
        </>
      )}
    </div>
  );
}
