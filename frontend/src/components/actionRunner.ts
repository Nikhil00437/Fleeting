/** Runs a note/task mutation and guarantees the user hears about the outcome.
 *
 * Several handlers in Inbox and NoteDrawer previously did
 * `await api.deleteNote(id)` inside an async onClick with no catch: a failed
 * request left the note on screen with no message, and in the drawer's case
 * meant `onClose()` never ran. This wrapper makes "report the failure" the
 * default rather than something each call site has to remember.
 */

import { errorMessage } from "./settingsState";

export type ActionToast = (message: string, kind?: "ok" | "err") => void;

export interface ActionSpec<TApi, TResult> {
  api: TApi;
  toast: ActionToast;
  action: (api: TApi) => Promise<TResult>;
  success: string;
  /** Runs only after the action resolved — e.g. removing the row from state. */
  onDone?: (result: TResult) => void;
}

export interface ActionResult<TResult> {
  ok: boolean;
  result?: TResult;
}

export async function runNoteAction<TApi, TResult>({
  api,
  toast,
  action,
  success,
  onDone,
}: ActionSpec<TApi, TResult>): Promise<ActionResult<TResult>> {
  let result: TResult;
  try {
    result = await action(api);
  } catch (e) {
    toast(errorMessage(e), "err");
    return { ok: false };
  }
  try {
    onDone?.(result);
  } catch (e) {
    toast(errorMessage(e), "err");
    return { ok: true, result };
  }
  toast(success, "ok");
  return { ok: true, result };
}