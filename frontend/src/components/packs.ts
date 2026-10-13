/** #495. Applying a theme is setting custom properties on the document root —
 * the tokens in `index.css` are already variables, so a pack overrides them
 * rather than replacing any stylesheet. */

import type { Pack } from "../types";

/** What `applyTokens` set, so it can be removed again. */
export type AppliedTokens = string[];

export function themeStyleText(tokens: Record<string, string>): string {
  const body = Object.entries(tokens)
    .map(([k, v]) => `${k}:${v}`)
    .join(";");
  return body ? `:root{${body}}` : "";
}

export function applyTokens(
  tokens: Record<string, string>,
  el: HTMLElement = document.documentElement
): AppliedTokens {
  const set: AppliedTokens = [];
  for (const [name, value] of Object.entries(tokens)) {
    el.style.setProperty(name, value);
    set.push(name);
  }
  return set;
}

/** Undo `applyTokens`. Without this a theme can only be replaced by another. */
export function clearTokens(applied: AppliedTokens, el: HTMLElement = document.documentElement): void {
  for (const name of applied) el.style.removeProperty(name);
}

export function findPack(packs: Pack[], name: string): Pack | undefined {
  return packs.find((p) => p.name === name);
}
