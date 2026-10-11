/**
 * #258 the entity index.
 *
 * Named "Entities" rather than "People" because that is what it is. The
 * extractor finds capitalised runs, so the list holds people ("Lisha Li"),
 * projects ("Omarchy"), tools ("Obsidian", "Qwen") and report headings
 * ("Daily Digest"). On a corpus that is mostly LLM-written digests those last
 * two are not people at all, and calling the page "People" would be a lie the
 * user has to discover for themselves.
 *
 * Mentions and note counts are shown as the two numbers they are. One note
 * naming Priya three times is three mentions and one note, and collapsing
 * them makes something that is discussed a lot look widely mentioned.
 */

import { useState } from "react";
import type { EntityNote, EntityRow } from "../types";

export function EntitiesView({
  people,
  selected,
  notes,
  loading,
  onSelect,
  onBack,
  onToast,
  resolveAlias,
}: {
  people: EntityRow[] | null;
  selected: string | null;
  notes: EntityNote[] | null;
  loading: boolean;
  onSelect: (name: string) => void;
  onBack: () => void;
  onToast: (msg: string, kind?: "ok" | "err") => void;
  resolveAlias: (alias: string, canonical: string) => Promise<{ ok: boolean }>;
}) {
  const [pending, setPending] = useState<string | null>(null);

  if (selected) {
    return (
      <EntityPage
        name={selected}
        notes={notes}
        onBack={onBack}
        resolveAlias={resolveAlias}
        pending={pending}
        setPending={setPending}
        onToast={onToast}
      />
    );
  }

  if (loading) {
    return (
      <div className="p-6 text-sm text-ink-500" aria-busy="true">
        Loading people…
      </div>
    );
  }

  if (!people || people.length === 0) {
    return (
      <div className="p-6 text-sm text-ink-500">
        Nothing to show yet. Names are picked out of your notes as you capture.
      </div>
    );
  }

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold text-ink-200">Entities</h2>
      <p className="mt-1 text-[11px] text-ink-500">
        {people.length} {people.length === 1 ? "name" : "names"} your notes keep mentioning —
        people, projects and tools. Names are picked out of the text as you capture.
      </p>
      <ul className="mt-3 divide-y divide-ink-800/70">
        {people.map((p) => (
          <li key={p.name}>
            <button
              type="button"
              onClick={() => onSelect(p.name)}
              className="flex w-full items-baseline justify-between gap-3 py-2 text-left hover:bg-ink-900/40"
            >
              <span className="text-sm text-ink-100">{p.name}</span>
              <span className="shrink-0 text-[11px] text-ink-500">
                {p.mentions} mentions · {p.notes_count} notes
              </span>
            </button>
            <p className="-mt-1 pb-1 text-[10px] text-ink-600">
              Last seen {p.last_seen ?? "—"}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EntityPage({
  name,
  notes,
  onBack,
  resolveAlias,
  pending,
  setPending,
  onToast,
}: {
  name: string;
  notes: EntityNote[] | null;
  onBack: () => void;
  resolveAlias: (alias: string, canonical: string) => Promise<{ ok: boolean }>;
  pending: string | null;
  setPending: (v: string | null) => void;
  onToast: (msg: string, kind?: "ok" | "err") => void;
}) {
  const rows = notes ?? [];
  return (
    <div className="p-4">
      <button
        type="button"
        onClick={onBack}
        className="micro-label mb-2 text-ink-500 hover:text-ink-300"
      >
        ← All people
      </button>
      <h2 className="text-sm font-semibold text-ink-200">{name}</h2>

      {rows.length === 0 ? (
        <p className="mt-3 text-xs text-ink-500">
          Nothing recorded for {name} yet.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {rows.map((n) => (
            <li key={n.id} className="rounded border border-ink-800/70 p-2">
              <p className="text-xs text-ink-100">{n.title || "(untitled)"}</p>
              {n.summary ? (
                <p className="mt-1 line-clamp-2 text-[11px] text-ink-500">{n.summary}</p>
              ) : null}
              {n.created_at ? (
                <p className="mt-1 text-[10px] text-ink-600">{n.created_at.slice(0, 10)}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      {/* #417: two people share a first name, so the user says which is which.
          That is an alias, not a guess the app should make. */}
      <AliasMerger
        name={name}
        pending={pending}
        setPending={setPending}
        resolveAlias={resolveAlias}
        onToast={onToast}
      />
    </div>
  );
}

function AliasMerger({
  name,
  pending,
  setPending,
  resolveAlias,
  onToast,
}: {
  name: string;
  pending: string | null;
  setPending: (v: string | null) => void;
  resolveAlias: (alias: string, canonical: string) => Promise<{ ok: boolean }>;
  onToast: (msg: string, kind?: "ok" | "err") => void;
}) {
  const [other, setOther] = useState("");

  return (
    <form
      className="mt-6 border-t border-ink-800/70 pt-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const canonical = other.trim();
        if (!canonical) return;
        setPending(name);
        try {
          const res = await resolveAlias(name, canonical);
          if (res?.ok) {
            onToast(`${name} merged into ${canonical}`, "ok");
            setOther("");
          } else {
            onToast(`${canonical} is not in the index yet`, "err");
          }
        } catch {
          onToast("Could not merge those names", "err");
        } finally {
          setPending(null);
        }
      }}
    >
      <label className="micro-label block text-ink-400" htmlFor="merge-into">
        This is actually someone else
      </label>
      <div className="mt-1 flex gap-2">
        <input
          id="merge-into"
          value={other}
          onChange={(e) => setOther(e.target.value)}
          placeholder="their full name"
          className="glass-studio flex-1 rounded px-2 py-1 text-xs text-ink-200"
        />
        <button
          type="submit"
          disabled={pending === name || !other.trim()}
          className="rounded px-2 py-1 text-xs text-ink-300 disabled:opacity-40"
        >
          Merge
        </button>
      </div>
    </form>
  );
}

export default EntitiesView;