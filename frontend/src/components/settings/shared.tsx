/** Shared bits for the settings tabs.
 *
 * `inputCls`/`labelCls` were local consts inside a 2000-line component; all
 * five tabs need them. Nothing else is abstracted — the repeated Tailwind
 * strings stay inline in the tabs, since wrapping them in a helper would hide
 * the styling for no gain.
 */

import type { Settings } from "../../types";

export const inputCls =
  "w-full rounded-xl border border-ink-700/90 bg-ink-950/90 px-3 py-2 text-xs text-ink-100 outline-none transition-colors focus:border-ember-500/50";

export const labelCls =
  "mb-1.5 block text-[10px] font-semibold tracking-wider text-ink-400 uppercase";

export type SaveFn = (
  changes: Record<string, unknown>,
  label?: string,
) => Promise<void>;

export type ToastFn = (message: string, kind?: "ok" | "err") => void;

export interface FormProps {
  /** Current settings; may be null only while the first load is in flight. */
  s: Settings;
  /** Applies a patch to settings; the parent reconciles with the server. */
  patch: (changes: Partial<Settings>) => void;
  save: SaveFn;
  saving: boolean;
}


export function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${
        checked ? "bg-ember-500 shadow-[0_0_10px_rgb(245_158_11/0.35)]" : "bg-ink-700"
      }`}
    >
      <span
        className="absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform duration-150"
        style={{ transform: checked ? "translateX(16px)" : "translateX(0)" }}
      />
    </button>
  );
}

/** Bytes to a human string; used for the whisper model download readout. */
export function fmtMB(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}
