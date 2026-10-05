/** #25: note colour palette shared by cards, the drawer swatches and the
 * vault-independent UI. A note's colour overrides the type accent on the
 * card's left border. Kept in a module (not a component) so it stays
 * testable with the SSR-string renderer. */

export interface NoteColor {
  name: string;
  hex: string;
}

export const NOTE_COLORS: NoteColor[] = [
  { name: "ember", hex: "#e8956d" },
  { name: "amber", hex: "#fbbf24" },
  { name: "emerald", hex: "#34d399" },
  { name: "cyan", hex: "#22d3ee" },
  { name: "iris", hex: "#a78bfa" },
  { name: "rose", hex: "#fb7185" },
];

export const NO_COLOR = "";

export function colorHex(name: string | null | undefined): string | null {
  if (!name) return null;
  return NOTE_COLORS.find((c) => c.name === name)?.hex ?? null;
}
