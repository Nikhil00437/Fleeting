/** #39 heatmap helpers — pure so vitest can pin the bucket scale. */

/** 0..4 bucket for a day's completion count. */
export function streakLevel(count: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0) return 0;
  if (count <= 2) return 1;
  if (count <= 4) return 2;
  if (count <= 7) return 3;
  return 4;
}

/** Split flat cells into columns of 7, oldest column first (Sunday rows). */
export function toWeeks(cells: Array<{ day: string; count: number }>): Array<Array<{ day: string; count: number }>> {
  const weeks: Array<Array<{ day: string; count: number }>> = [];
  for (let i = 0; i < cells.length; i += 7) {
    weeks.push(cells.slice(i, i + 7));
  }
  return weeks;
}