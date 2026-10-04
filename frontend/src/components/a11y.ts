/** Keyboard activation for clickable non-button elements.
 *
 * A `<div onClick>` or `<article onClick>` is invisible to the keyboard: not
 * focusable, no role, no way to activate. The note cards were the app's primary
 * content surface, so this made the whole inbox keyboard-dead.
 *
 * Native `<button>` already does all of this, so prefer it where the markup
 * allows. This exists for the card/article case where a button cannot be used.
 */

export type ActivationKind = "keydown" | "keyup" | "keypress";

/** True for the keys that mean "activate this control". */
export function isActivationKey(key: string, kind: ActivationKind = "keydown"): boolean {
  if (key === "Enter") return true;
  // Only keydown counts for Space: keyup would double-fire alongside the click
  // that a browser synthesises for a real button.
  return kind === "keydown" && (key === " " || key === "Spacebar");
}

export interface ActivationProps {
  role: "button";
  tabIndex: 0;
  "aria-label": string;
  onKeyDown: (e: { key: string; preventDefault: () => void }) => void;
}

/**
 * Props that make a non-button element behave like one.
 *
 * `label` becomes the accessible name, since an article's text content is not
 * reliably announced as its name.
 */
export function noteCardActivationProps(label: string, onActivate?: () => void): ActivationProps {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    onKeyDown: (e) => {
      if (!isActivationKey(e.key)) return;
      e.preventDefault();
      onActivate?.();
    },
  };
}