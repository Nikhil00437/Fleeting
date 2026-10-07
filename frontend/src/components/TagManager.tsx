import { useEffect, useState } from "react";
import { api } from "../api";
import { errorMessage } from "./settingsState";
import { EditIcon, TrashIcon, XIcon } from "./Icons";
import type { TagCount } from "../types";

interface AuditPair {
  tags: string[];
  target: string;
}

interface AuditData {
  rare: { tag: string; count: number }[];
  overlapping: AuditPair[];
  misspelt: AuditPair[];
}

interface Props {
  onClose: () => void;
  /** Called after any mutation so the parent can refetch tag counts. */
  onChanged?: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
}

/**
 * #50 tag manager (rename / merge / delete) + #425 tag audit
 * (rare, overlapping, misspelt candidates with one-click merges).
 * All mutations go through the tag endpoints, which emit note.updated
 * per affected note — this panel only refetches its own lists.
 */
export default function TagManager({ onClose, onChanged, onToast }: Props) {
  const [tags, setTags] = useState<TagCount[]>([]);
  const [audit, setAudit] = useState<AuditData | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [mergeTarget, setMergeTarget] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api.tags().then(setTags).catch(() => {});
    api.tagsAudit().then(setAudit).catch(() => setAudit(null));
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(action: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await action();
      onToast(ok);
      onChanged?.();
      setSelected([]);
      setMergeTarget("");
      load();
    } catch (e) {
      onToast(errorMessage(e), "err");
    } finally {
      setBusy(false);
    }
  }

  function toggleSelect(tag: string) {
    setSelected((cur) => (cur.includes(tag) ? cur.filter((t) => t !== tag) : [...cur, tag]));
  }

  const section = "rounded-xl border border-ink-800/80 bg-ink-950/60 p-3";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-label="Tag manager"
        className="glass-studio max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink-100">Tag manager</h2>
            <p className="text-[11px] text-ink-400">
              Rename, merge or remove tags across every note. Changes propagate live.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close tag manager"
            className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        {/* Merge bar for multi-selection */}
        <div className={`${section} mb-4 flex flex-wrap items-center gap-2`}>
          <span className="micro-label">
            {selected.length > 0 ? `${selected.length} selected` : "Select tags below to merge"}
          </span>
          {selected.length > 0 && (
            <>
              <input
                value={mergeTarget}
                onChange={(e) => setMergeTarget(e.target.value)}
                placeholder="merge into…"
                aria-label="Merge target tag"
                className="h-7 w-40 rounded-lg border border-ink-800 bg-ink-950 px-2 font-mono text-[11px] text-ink-100 outline-none focus:border-ember-500/50"
              />
              <button
                disabled={busy || !mergeTarget.trim()}
                onClick={() =>
                  run(
                    () => api.mergeTags(selected, mergeTarget.trim()),
                    `Merged ${selected.length} tag${selected.length === 1 ? "" : "s"} into #${mergeTarget.trim()}`,
                  )
                }
                className="rounded-lg bg-ember-500/20 px-2.5 py-1 text-[11px] font-semibold text-ember-300 hover:bg-ember-500/30 disabled:opacity-40"
              >
                Merge
              </button>
              <button
                onClick={() => setSelected([])}
                className="rounded-lg px-2 py-1 text-[11px] text-ink-400 hover:text-ink-200"
              >
                Clear
              </button>
            </>
          )}
        </div>

        {/* All tags */}
        <div className={`${section} mb-4`}>
          <p className="micro-label mb-2">All tags ({tags.length})</p>
          {tags.length === 0 ? (
            <p className="text-xs text-ink-500">No tags yet.</p>
          ) : (
            <ul className="max-h-64 space-y-0.5 overflow-y-auto">
              {tags.map(({ tag, count }) => (
                <li key={tag} className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-ink-900/70">
                  <input
                    type="checkbox"
                    checked={selected.includes(tag)}
                    onChange={() => toggleSelect(tag)}
                    aria-label={`Select tag ${tag} for merge`}
                    className="h-3.5 w-3.5 accent-ember-400"
                  />
                  {renaming === tag ? (
                    <form
                      className="flex min-w-0 flex-1 items-center gap-1.5"
                      onSubmit={(e) => {
                        e.preventDefault();
                        const to = renameValue.trim();
                        if (!to || to === tag) {
                          setRenaming(null);
                          return;
                        }
                        setRenaming(null);
                        void run(() => api.renameTag(tag, to), `Renamed #${tag} → #${to}`);
                      }}
                    >
                      <input
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        autoFocus
                        aria-label={`New name for ${tag}`}
                        className="h-6 min-w-0 flex-1 rounded-md border border-ember-500/40 bg-ink-950 px-2 font-mono text-[11px] text-ink-100 outline-none"
                      />
                      <button type="submit" className="text-[11px] font-semibold text-ember-300 hover:text-ember-200">
                        Save
                      </button>
                    </form>
                  ) : (
                    <>
                      <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink-200">#{tag}</span>
                      <span className="rounded-md bg-ink-900/90 px-1.5 py-0.2 font-mono text-[10px] text-ink-400">
                        {count}
                      </span>
                      <button
                        onClick={() => {
                          setRenaming(tag);
                          setRenameValue(tag);
                        }}
                        aria-label={`Rename tag ${tag}`}
                        className="rounded p-1 text-ink-500 hover:bg-white/[0.06] hover:text-ink-100"
                      >
                        <EditIcon className="h-3 w-3" />
                      </button>
                      <button
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm(`Remove #${tag} from all notes? Notes themselves stay.`)) {
                            void run(() => api.deleteTag(tag), `Removed #${tag} from all notes`);
                          }
                        }}
                        aria-label={`Delete tag ${tag}`}
                        className="rounded p-1 text-ink-500 hover:bg-red-500/10 hover:text-red-300"
                      >
                        <TrashIcon className="h-3 w-3" />
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* #425 audit */}
        {audit && (
          <div className="grid gap-3 md:grid-cols-3">
            <div className={section}>
              <p className="micro-label mb-1.5">Rare (1 use)</p>
              {audit.rare.length === 0 ? (
                <p className="text-[11px] text-ink-500">Nothing rare.</p>
              ) : (
                <div className="flex flex-wrap gap-1">
                  {audit.rare.map((r) => (
                    <button
                      key={r.tag}
                      onClick={() => toggleSelect(r.tag)}
                      title="Click to select for merging"
                      className="rounded-md border border-white/[0.06] bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10.5px] text-ink-300 hover:border-ember-400/40 hover:text-ember-200"
                    >
                      #{r.tag}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {(
              [
                ["Overlapping", audit.overlapping],
                ["Likely misspelt", audit.misspelt],
              ] as const
            ).map(([label, pairs]) => (
              <div key={label} className={section}>
                <p className="micro-label mb-1.5">{label}</p>
                {pairs.length === 0 ? (
                  <p className="text-[11px] text-ink-500">Nothing found.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {pairs.map((p) => (
                      <li key={p.tags.join("|")} className="flex items-center gap-1.5">
                        <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-ink-300">
                          #{p.tags.join(" · #")}
                        </span>
                        <button
                          disabled={busy}
                          onClick={() =>
                            run(
                              () => api.mergeTags(p.tags, p.target),
                              `Merged into #${p.target}`,
                            )
                          }
                          className="shrink-0 rounded-md border border-ember-500/30 bg-ember-500/10 px-1.5 py-0.5 text-[10px] font-medium text-ember-300 hover:bg-ember-500/20"
                          title={`Merge into #${p.target}`}
                        >
                          → #{p.target}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
