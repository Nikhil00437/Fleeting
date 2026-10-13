/** #137. Bytes come from the backend's filesystem walk, never from summing
 * column lengths — a blob, an audio file and a row of text are not comparable,
 * and `length()` under-reports by the page overhead SQLite actually spends. */

import type { InventoryCategory } from "../types";

export type { InventoryCategory };

export function formatBytes(n: number): string {
  // A negative size means the number upstream is wrong. Rendering "-1.0 kB"
  // would hide that, so it collapses to zero instead.
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  const units = ["B", "kB", "MB", "GB", "TB"];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

export function describeInventory(categories: InventoryCategory[]): string {
  if (!categories.length) return "Nothing stored yet.";
  const biggest = categories[0];
  const trashed = categories.reduce((n, c) => n + (c.count_deleted ?? 0), 0);
  const trashedNote = trashed ? ` ${trashed} trashed, still on disk.` : "";
  return `Largest: ${biggest.name} at ${formatBytes(biggest.bytes)}.${
    biggest.deletable ? "" : " Not removable from here."
  }${trashedNote}`;
}
