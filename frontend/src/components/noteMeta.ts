/** #476 tl;dr + #477 word count / reading time, #96 enrichment confidence.
 *
 * Pure module per repo convention: list-view derivations live outside the
 * component so the SSR-string tests can exercise them.
 */

const READ_WPM = 200;
const TLDR_MAX = 140;

/** Below this, the enrichment is worth a second look (#96). */
export const LOW_CONFIDENCE = 0.7;

/** "91% confident", or null when there is no score to report. */
export function describeConfidence(confidence: number | null | undefined): string | null {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) return null;
  const pct = Math.round(confidence * 100);
  return pct < LOW_CONFIDENCE * 100 ? `${pct}% confident — worth checking` : `${pct}% confident`;
}

export function wordCount(text: string | null | undefined): number {
  const t = (text ?? "").trim();
  if (!t) return 0;
  return t.split(/\s+/).length;
}

/** Rough reading time in whole minutes, minimum 1 for any non-empty text. */
export function readingMinutes(text: string | null | undefined): number {
  const words = wordCount(text);
  if (words === 0) return 0;
  return Math.max(1, Math.round(words / READ_WPM));
}

function firstSentence(text: string): string {
  const m = text.match(/^[\s\S]*?[.!?](?:\s|$)/);
  const sentence = (m ? m[0] : text).trim();
  return sentence;
}

/** #476: one-line summary for list views — first sentence of the AI summary,
 * falling back to the note body. Hard-capped so list rows stay one line. */
export function tldr(note: { summary?: string | null; raw_text?: string | null; title?: string | null }): string {
  const source = (note.summary ?? "").trim() || (note.raw_text ?? "").trim();
  if (!source) return "";
  let line = firstSentence(source.replace(/\s+/g, " "));
  if (line.length > TLDR_MAX) line = line.slice(0, TLDR_MAX - 1).trimEnd() + "…";
  return line;
}
