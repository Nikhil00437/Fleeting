/**
 * #446 rewrite menu, #447 title suggestions, #261 dictated-text cleanup.
 *
 * Four APIs shipped with no surface at all. This is where they are reached.
 *
 * Nothing applies automatically. A rewrite is offered with Accept and Discard
 * because the backend rule is that a rewrite the user did not accept must not
 * have replaced their words — an auto-saving button would quietly break it.
 *
 * When cleanup reports words it invented, they are named. That report is the
 * feature (#261): a reword the user cannot see is the thing "keep my wording"
 * exists to prevent.
 */

import { useState } from "react";
import type { WritingResult } from "../types";

const STYLE_LABELS: Record<string, string> = {
  shorter: "Shorter",
  clearer: "Clearer",
  friendlier: "Friendlier",
  "more formal": "More formal",
};

export function WritingMenu({
  text,
  styles,
  result,
  titles,
  showTitles,
  error,
  busy,
  onApply,
  onRun,
  onTitle,
  onToast,
  onKeepWording,
}: {
  text: string;
  styles?: string[];
  result: WritingResult | null;
  titles?: string[];
  showTitles?: boolean;
  error?: string | null;
  busy?: boolean;
  onApply: (text: string) => void;
  onRun?: (style: string) => void;
  onTitle?: (title: string) => void;
  onToast: (msg: string, kind?: "ok" | "err") => void;
  onKeepWording?: (v: boolean) => void;
}) {
  const [keepWording, setKeepWording] = useState(true);
  const menu = styles && styles.length ? styles : Object.keys(STYLE_LABELS);

  if (!text || !text.trim()) {
    return (
      <p className="px-3 py-2 text-[11px] text-ink-500">
        Select some text first — there is nothing to rewrite.
      </p>
    );
  }

  return (
    <div className="border-t border-ink-800/80 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {menu.map((style) => (
          <button
            key={style}
            type="button"
            disabled={busy}
            onClick={() => onRun?.(style)}
            className="rounded border border-ink-700 px-2 py-0.5 text-[11px] text-ink-300 hover:border-ink-500 disabled:opacity-40"
          >
            {STYLE_LABELS[style] ?? style}
          </button>
        ))}
        <button
          type="button"
          disabled={busy}
          onClick={() => onRun?.("cleaner")}
          className="rounded border border-ink-700 px-2 py-0.5 text-[11px] text-ink-300 hover:border-ink-500 disabled:opacity-40"
        >
          Clean up
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onRun?.("titles")}
          className="rounded border border-ink-700 px-2 py-0.5 text-[11px] text-ink-300 hover:border-ink-500 disabled:opacity-40"
        >
          Suggest titles
        </button>
      </div>

      {/* #261: on by default, because it is the default the user wants from a
          cleanup. Turning it off is a deliberate act, not a default. */}
      <label className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-400">
        <input
          type="checkbox"
          checked={keepWording}
          onChange={(e) => {
            setKeepWording(e.target.checked);
            onKeepWording?.(e.target.checked);
          }}
        />
        Keep my wording when cleaning up dictated text
      </label>

      {error ? (
        <p className="mt-2 text-[11px] text-rose-400">{error}</p>
      ) : null}

      {showTitles && titles && titles.length ? (
        <ul className="mt-2 space-y-1">
          {titles.map((title) => (
            <li key={title}>
              <button
                type="button"
                onClick={() => onTitle?.(title)}
                className="text-left text-[11px] text-ink-200 hover:text-ink-100"
              >
                {title}
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {result && !error ? (
        <div className="mt-2 rounded border border-ink-700/80 p-2">
          <p className="text-[11px] text-ink-200">{result.text}</p>

          {result.kept_wording === false && result.added_words?.length ? (
            <p className="mt-1 text-[10px] text-amber-400">
              Added words you did not say: {result.added_words.join(", ")}
            </p>
          ) : null}

          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => {
                onApply(result.text);
                onToast("Applied", "ok");
              }}
              className="rounded border border-ink-600 px-2 py-0.5 text-[11px] text-ink-200 hover:border-ink-400"
            >
              Accept
            </button>
            <button
              type="button"
              onClick={() => onApply("")}
              className="rounded border border-ink-800 px-2 py-0.5 text-[11px] text-ink-500 hover:border-ink-600"
            >
              Discard
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default WritingMenu;