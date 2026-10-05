/**
 * Who is allowed to end a process.
 *
 * Fleeting runs as the desktop user, so it cannot signal anything owned by
 * root. The process table lists the whole machine — 169 of 199 rows are root
 * owned on a typical desktop — and offered "End" on every one, so the only
 * feedback was a 403 "Access denied" after the fact.
 *
 * The API already returns `username` per process, so the client can tell the
 * user up front instead of letting the OS refuse at them.
 */

export interface OwnedProcess {
  username?: string | null;
}

/** Only processes owned by the current user can be signalled. */
export function canSignal(p: OwnedProcess | null | undefined, currentUser: string): boolean {
  const owner = (p?.username ?? "").trim();
  const me = (currentUser ?? "").trim();
  // Unknown owner is not assumed signalable — better a disabled button than a
  // 403.
  return owner !== "" && me !== "" && owner === me;
}

/** Empty string when the process can be ended; otherwise why it cannot. */
export function killBlockedReason(
  p: OwnedProcess | null | undefined,
  currentUser: string,
): string {
  if (canSignal(p, currentUser)) return "";
  const owner = (p?.username ?? "").trim() || "another user";
  const me = (currentUser ?? "").trim() || "this user";
  return `Owned by ${owner}. Fleeting runs as ${me} and cannot end it — try sudo from a terminal.`;
}
