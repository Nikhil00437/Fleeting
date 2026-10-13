/** #100: what is missing, with the command that fixes it. */
import type { PreflightCheck } from "../types";
import { describePreflight } from "./preflight";

function Row({ c }: { c: PreflightCheck }) {
  return (
    <li className="flex items-start gap-2 py-1">
      <span
        aria-hidden="true"
        className={`mt-[3px] font-mono text-[10px] ${c.ok ? "text-ink-500" : "text-amber-300"}`}
      >
        {c.ok ? "✓" : c.required ? "✗" : "!"}
      </span>
      <div className="min-w-0">
        <p className="text-[11px] text-ink-200">
          {c.name}
          {c.required && <span className="ml-1.5 text-[9px] text-ink-500">required</span>}
        </p>
        <p className="text-[10px] leading-relaxed text-ink-500">{c.detail}</p>
        {c.fix && <p className="font-mono text-[10px] leading-relaxed text-amber-300/90">{c.fix}</p>}
      </div>
    </li>
  );
}

export default function PreflightCard({
  checks,
  error,
}: {
  checks: PreflightCheck[] | null;
  error?: string;
}) {
  if (error) {
    return <p className="text-[11px] text-amber-300">Could not check dependencies: {error}</p>;
  }
  if (!checks) return null;
  return (
    <div className="space-y-1">
      <ul className="divide-y divide-white/[0.04]">
        {checks.map((c) => (
          <Row key={c.name} c={c} />
        ))}
      </ul>
      <p className="pt-1 text-[10px] text-ink-500">{describePreflight(checks)}</p>
    </div>
  );
}
