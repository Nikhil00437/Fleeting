export function parseDate(iso: string): Date {
  return new Date(iso);
}

export function timeOfDay(iso: string): string {
  return parseDate(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function relTime(iso: string): string {
  const then = parseDate(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  return parseDate(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

export function dayGroup(iso: string): string {
  const d = parseDate(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const t = d.getTime();
  if (t >= startOfToday) return "Today";
  if (t >= startOfToday - 86_400_000) return "Yesterday";
  if (t >= startOfToday - 6 * 86_400_000) return "This week";
  return d.toLocaleDateString([], { month: "long", year: "numeric" });
}

export function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
