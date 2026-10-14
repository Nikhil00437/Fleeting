// #458: the read-only demo banner.
//
// The API enforces read-only in middleware, so this component is not what makes
// demo mode safe — it is what stops a visitor spending a minute discovering it
// by trying to type a note and watching the save fail.
//
// Deliberately a status region, not an alert: it is permanent while the mode is
// on, and a `role="alert"` announces itself to a screen reader every time the
// app re-renders.

export interface DemoStatus {
  demo_mode: boolean;
  reads_only: boolean;
  turn_off: string;
}

/** Only a banner worth showing is rendered at all. */
export function shouldShowDemoBanner(
  status: DemoStatus | null,
): boolean {
  return status?.demo_mode === true;
}

export function DemoBanner({ status }: { status: DemoStatus | null }) {
 if (!shouldShowDemoBanner(status)) return null;
 return (
  <div
   role="status"
   className="flex items-center justify-center gap-2 border-b border-sky-900 bg-sky-950/60 px-3 py-1.5 text-xs text-sky-200"
  >
   <span aria-hidden="true">◆</span>
   <span>
    Read-only demo — browsing works, saving does not.
   </span>
  </div>
 );
}
