/** Run a state change inside a View Transition when the browser supports it. */
export function vt(update: () => void) {
  const d = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  if (!d.startViewTransition || matchMedia("(prefers-reduced-motion: reduce)").matches) return update();
  d.startViewTransition(update);
}
