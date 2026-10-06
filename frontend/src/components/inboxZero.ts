/** #419 inbox-zero ritual: how much of today's inbox is actually filed. */

export interface InboxZeroNote {
  created_at: string;
  review_state?: string | null;
  status: string;
  archived?: boolean;
  trashed_at?: string | null;
}

export function inboxZeroProgress(
  notes: InboxZeroNote[],
  startOfDayMs: number
): { total: number; filed: number; progress: number } {
  const todays = notes.filter((n) => new Date(n.created_at).getTime() >= startOfDayMs);
  // Filed means reviewed or shelved. A note the pipeline finished but nobody
  // looked at is still sitting in the inbox, so it counts against zero.
  const filed = todays.filter(
    (n) => n.review_state !== "raw" || Boolean(n.archived) || Boolean(n.trashed_at)
  ).length;
  return { total: todays.length, filed, progress: todays.length ? filed / todays.length : 1 };
}