/** #495: browse and install packs. Reads from ~/.config/fleeting/packs/ by
 * default; a `dir` prop points it at a folder elsewhere. */
import type { Pack } from "../types";

export default function PackList({
  packs,
  errors = [],
  error,
  dir,
  onInstall,
}: {
  packs: Pack[] | null;
  errors?: string[];
  error?: string | null;
  dir?: string;
  onInstall: (name: string) => void;
}) {
  if (error) {
    return <p className="text-[11px] text-amber-300">Could not read packs: {error}</p>;
  }
  if (!packs) return null;
  const where = dir ?? "~/.config/fleeting/packs/";
  return (
    <div className="space-y-2">
      {packs.length === 0 ? (
        <p className="text-[11px] leading-relaxed text-ink-400">
          No packs found in <span className="font-mono text-ink-300">{where}</span>. Drop a{" "}
          <span className="font-mono text-ink-300">.json</span> file in there — a pack is just a theme and
          some prompts.
        </p>
      ) : (
        <ul className="space-y-2">
          {packs.map((p) => (
            <li
              key={p.name}
              className="flex items-start justify-between gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] p-3"
            >
              <div className="min-w-0">
                <p className="text-xs text-ink-100">
                  {p.name}
                  {p.active && <span className="ml-2 text-[10px] text-ink-500">installed</span>}
                </p>
                {p.description && <p className="text-[11px] text-ink-400">{p.description}</p>}
                {Object.keys(p.prompts).length > 0 && (
                  <p className="mt-1 font-mono text-[10px] text-ink-500">
                    sets: {Object.keys(p.prompts).join(", ")}
                  </p>
                )}
              </div>
              {!p.active && (
                <button
                  type="button"
                  onClick={() => onInstall(p.name)}
                  className="shrink-0 cursor-pointer rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:border-ember-400/40"
                  data-testid={`install-${p.name}`}
                >
                  Install
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {errors.length > 0 && (
        <ul className="space-y-0.5">
          {errors.map((e) => (
            <li key={e} className="font-mono text-[10px] text-amber-300/80">
              {e}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
