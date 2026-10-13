/** #455. Pure, so it is testable with the SSR renderer rather than inside a
 * handler where a regression is invisible until someone clicks Delete. */

import type { BulkPreview } from "../types";

const MAX_SHOWN = 5;

export function describeBulkRefusal(p: BulkPreview): string {
  const noun = p.count === 1 ? "note" : "notes";
  const shown = p.samples.slice(0, MAX_SHOWN).map((s) => s.title || "(untitled)");
  const more = p.samples.length > MAX_SHOWN ? ` and ${p.samples.length - MAX_SHOWN} more` : "";
  if (!shown.length) return `${p.count} ${noun} would be permanently deleted.`;
  return `${p.count} ${noun} would be permanently deleted: ${shown.join(", ")}${more}.`;
}
