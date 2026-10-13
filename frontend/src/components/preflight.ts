/** #100. Pure, so it is testable with the SSR renderer instead of inside a
 * useEffect where a regression is invisible. */

import type { PreflightCheck } from "../types";

export function missingRequired(checks: PreflightCheck[]): string[] {
  return checks.filter((c) => c.required && !c.ok).map((c) => c.name);
}

export function describePreflight(checks: PreflightCheck[]): string {
  if (!checks.length) return "Checking dependencies…";
  const broken = checks.filter((c) => !c.ok);
  if (!broken.length) return "Everything this app can use is installed.";
  const required = broken.filter((c) => c.required);
  if (required.length) {
    return `${required.length} required ${required.length === 1 ? "thing is" : "things are"} missing — ${required
      .map((c) => c.name)
      .join(", ")}. The app cannot work fully until ${required.length === 1 ? "this is" : "these are"} fixed.`;
  }
  return `${broken.length} optional ${broken.length === 1 ? "thing is" : "things are"} missing: ${broken
    .map((c) => c.name)
    .join(", ")}. Everything else works.`;
}
