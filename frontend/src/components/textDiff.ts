/** #21: raw-transcript vs cleaned-text diff.
 *
 * Word-level LCS. Kept in a pure module so it renders/compares identically
 * in tests (node env, no DOM). LCS is O(n*m): transcripts beyond the size
 * cap degrade to a plain "changed" pair rather than freezing the drawer.
 */

export interface DiffPart {
  type: "same" | "add" | "del";
  text: string;
}

const MAX_TOKENS = 4000;

function lcsDiff(a: string[], b: string[]): DiffPart[] {
  const n = a.length;
  const m = b.length;
  // dp[i][j] = LCS length of a[i:], b[j:]
  const dp: Uint16Array[] = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const parts: DiffPart[] = [];
  let i = 0;
  let j = 0;
  const push = (type: DiffPart["type"], text: string) => {
    const last = parts[parts.length - 1];
    if (last && last.type === type) last.text += text;
    else parts.push({ type, text });
  };
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("del", a[i]);
      i++;
    } else {
      push("add", b[j]);
      j++;
    }
  }
  while (i < n) push("del", a[i++]);
  while (j < m) push("add", b[j++]);
  return parts;
}

function tokenize(text: string): string[] {
  return text.split(/(\s+)/).filter((t) => t.length > 0);
}

export function diffText(original: string, current: string): DiffPart[] {
  const a = tokenize(original);
  const b = tokenize(current);
  if (a.length > MAX_TOKENS || b.length > MAX_TOKENS) {
    const parts: DiffPart[] = [];
    if (original) parts.push({ type: "del", text: original });
    if (current) parts.push({ type: "add", text: current });
    return parts;
  }
  return lcsDiff(a, b);
}

/** Stats for a compact badge: how much of the original survives. */
export function diffStats(parts: DiffPart[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const p of parts) {
    const words = p.text.trim() ? p.text.trim().split(/\s+/).length : 0;
    if (p.type === "add") added += words;
    else if (p.type === "del") removed += words;
  }
  return { added, removed };
}
