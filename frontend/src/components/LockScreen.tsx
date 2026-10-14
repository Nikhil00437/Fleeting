// #135: the unlock screen.
//
// A full-screen gate rather than a modal: while locked, nothing behind it is
// readable, so presenting anything behind it would be a lie about what the app
// is doing.
//
// No token is stored in the browser. Unlocking is per-server-process, so the
// token is needed for exactly one request — changing the passphrase — and
// keeping a credential in `sessionStorage` for a session that would not use it
// is a key left in the door for no benefit.

import { useState } from "react";

export interface LockStatus {
  enabled: boolean;
  configured: boolean;
  locked: boolean;
  retry_in: number;
}

/** The header the one request that needs a token carries it in. */
export const LOCK_HEADER = "x-fleeting-lock";

export function LockScreen({
  status,
  onUnlock,
}: {
  status: LockStatus;
  onUnlock: (passphrase: string) => Promise<string>;
}) {
 const [value, setValue] = useState("");
 const [error, setError] = useState("");
 const [busy, setBusy] = useState(false);

 async function submit(e: React.FormEvent) {
  e.preventDefault();
  setBusy(true);
  setError("");
  try {
   await onUnlock(value);
   setValue("");
  } catch (err) {
   setError(err instanceof Error ? err.message : "could not unlock");
  } finally {
   setBusy(false);
  }
 }

 return (
  <div className="app-root flex h-screen w-screen items-center justify-center bg-ink-950">
   <form
    onSubmit={submit}
    className="glass-studio flex w-80 flex-col gap-3 rounded-xl p-6"
    aria-label="Unlock"
   >
    <h1 className="text-sm font-medium text-ink-100">Locked</h1>
    <p className="text-xs text-ink-400">
     This app is locked. Enter the passphrase to continue.
    </p>
    <label className="micro-label" htmlFor="lock-passphrase">
     Passphrase
    </label>
    <input
     id="lock-passphrase"
     type="password"
     autoFocus
     value={value}
     onChange={(e) => setValue(e.target.value)}
     className="rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-100"
    />
    {error && (
     <p role="alert" className="text-xs text-red-300">
      {error}
     </p>
    )}
    <button
     type="submit"
     disabled={busy || value.length === 0}
     className="rounded-md bg-ink-700 px-3 py-2 text-sm text-ink-50 disabled:opacity-50"
    >
     {busy ? "Unlocking…" : "Unlock"}
    </button>
    {status.retry_in > 0 && (
     <p role="status" className="text-xs text-amber-300">
      Too many attempts. Try again in {Math.ceil(status.retry_in)}s.
     </p>
    )}
   </form>
  </div>
 );
}
