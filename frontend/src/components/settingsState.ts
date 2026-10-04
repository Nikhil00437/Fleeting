/** Pure helpers for the settings form's optimistic save.
 *
 * The form shows a value as soon as it is typed, then reconciles with whatever
 * the server actually stored. Extracted from the component because `useEffect`
 * bodies cannot be exercised by the SSR-string renderer the other tests use.
 */

/** Apply a pending change locally, without mutating the previous object. */
export function applySettingsChange<T extends object>(current: T, changes: Partial<T>): T {
  return { ...current, ...changes };
}

/**
 * Settle an optimistic save.
 *
 * `server` is the authoritative response when present; on failure pass null and
 * the snapshot taken before the edit is restored, so the input can never keep
 * showing a value that was never persisted.
 */
export function reconcileSettings<T extends object>(
  _optimistic: T,
  previous: T,
  server: T | null,
): T {
  return server ?? previous;
}

/** A message that is always safe to show in a toast. */
export function errorMessage(e: unknown): string {
  if (e instanceof Error && e.message.trim()) return e.message;
  const s = typeof e === "string" ? e.trim() : "";
  return s || "Something went wrong";
}