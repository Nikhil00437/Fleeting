/** #270: nested tags (`work/client-a/billing`) as a tree.
 *
 * Tags are flat strings in the DB; nesting is a naming convention, so the
 * tree is derived at render time. Pure module per repo convention.
 */

import type { TagCount } from "../types";

export interface TagNode {
  /** Last path segment, e.g. "billing". */
  name: string;
  /** Full tag path, e.g. "work/client-a/billing". */
  full: string;
  /** Notes carrying exactly this tag. */
  own: number;
  /** Notes carrying this tag or any descendant. */
  total: number;
  children: TagNode[];
}

export function buildTagTree(tags: TagCount[]): TagNode[] {
  const roots: TagNode[] = [];
  /** Full path -> node, so duplicate prefixes merge across entries. */
  const byPath = new Map<string, TagNode>();

  for (const { tag, count } of tags) {
    const parts = tag.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    let full = "";
    let node: TagNode | undefined;
    for (const part of parts) {
      full = full ? `${full}/${part}` : part;
      node = byPath.get(part === full ? part : full);
      if (!node) {
        node = { name: part, full, own: 0, total: 0, children: [] };
        byPath.set(full, node);
        if (full === part) roots.push(node);
        else {
          const parentFull = full.slice(0, full.length - part.length - 1);
          const parent = byPath.get(parentFull);
          if (parent) parent.children.push(node);
        }
      }
    }
    if (node) node.own += count;
  }

  const rollup = (node: TagNode): number => {
    node.total = node.own + node.children.reduce((sum, c) => sum + rollup(c), 0);
    return node.total;
  };
  for (const r of roots) rollup(r);

  const sortTree = (nodes: TagNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    for (const n of nodes) sortTree(n.children);
  };
  sortTree(roots);
  return roots;
}

/** A selection matches a tag exactly or as an ancestor ("work" covers "work/x"). */
export function tagMatches(tag: string, selected: string | null | undefined): boolean {
  if (!selected) return false;
  return tag === selected || tag.startsWith(`${selected}/`);
}

/** Flatten a tree for a11y-friendly ordered rendering with depth hints. */
export function flattenTagTree(nodes: TagNode[], depth = 0): Array<{ node: TagNode; depth: number }> {
  const out: Array<{ node: TagNode; depth: number }> = [];
  for (const n of nodes) {
    out.push({ node: n, depth });
    out.push(...flattenTagTree(n.children, depth + 1));
  }
  return out;
}

/** #420: normalise what triage's tag box produced ("#Health" -> "health"). */
export function normalizeTag(input: string): string {
  return input.trim().replace(/^#/, "").toLowerCase();
}
