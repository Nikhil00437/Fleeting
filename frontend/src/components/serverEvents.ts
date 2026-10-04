/** Pure reducer for server-sent events.
 *
 * The SSE handler in `App.tsx` was an if-chain that handled note, activity,
 * whisper and dailylog events — but not `task.*`, which the backend publishes
 * from seven call sites. Tasks created or edited by the vault watcher were
 * therefore invisible in the Tasks view until you navigated away and back.
 *
 * Extracted so the whole mapping is testable: the component version lives
 * inside a `useEffect`, which the SSR-string test renderer never runs.
 */

export interface ServerNote {
  id: string;
  title?: string;
  status?: string;
}

export interface ServerState {
  liveApp: string | null;
  whisper: Record<string, unknown> | null;
  timelineKey: number;
  tasksKey: number;
  notes: ServerNote[];
  /** Raw latest embedding-migration payload, if any. */
  embedding: Record<string, unknown> | null;
}

/** What the caller should do after applying an event. */
export interface ServerEffects {
  refreshStats: boolean;
  toast: string | null;
}

export interface RawEvent {
  type?: string;
  data?: unknown;
}

export function emptyServerState(): ServerState {
  return {
    liveApp: null,
    whisper: null,
    timelineKey: 0,
    tasksKey: 0,
    notes: [],
    embedding: null,
  };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null ? (v as Record<string, unknown>) : null;
}

/** Insert or replace a note by id, preserving order. */
function upsertNote(notes: ServerNote[], incoming: ServerNote): ServerNote[] {
  const idx = notes.findIndex((n) => n.id === incoming.id);
  if (idx === -1) return [...notes, incoming];
  const next = notes.slice();
  next[idx] = { ...next[idx], ...incoming };
  return next;
}

/**
 * Apply one event to the state. Returns the same object when nothing changes,
 * so callers can use identity to skip re-renders.
 */
export function applyServerEvent(
  state: ServerState,
  event: RawEvent,
): ServerState & ServerEffects {
  const noEffects = { refreshStats: false, toast: null };
  const type = typeof event?.type === "string" ? event.type : "";
  const data = asRecord(event?.data);
  if (!type || data === null) return { ...state, ...noEffects };

  switch (type) {
    case "note.created":
    case "note.updated": {
      const id = typeof data.id === "string" ? data.id : null;
      if (!id) return { ...state, ...noEffects };
      const incoming = { ...(data as object), id } as ServerNote;
      return {
        ...state,
        notes: upsertNote(state.notes, incoming),
        ...noEffects,
        refreshStats: data.status === "done",
      };
    }
    case "note.deleted": {
      const id = typeof data.id === "string" ? data.id : null;
      if (!id) return { ...state, ...noEffects };
      return {
        ...state,
        notes: state.notes.filter((n) => n.id !== id),
        refreshStats: true,
        toast: null,
      };
    }
    case "task.created":
    case "task.updated":
    case "task.deleted":
      // The Tasks view refetches on this key. Without it, vault-watcher edits
      // were invisible until the view remounted.
      return { ...state, tasksKey: state.tasksKey + 1, ...noEffects };

    case "activity.live": {
      const session = asRecord(data.session);
      const app = session?.app_class;
      return {
        ...state,
        liveApp: typeof app === "string" ? app : null,
        ...noEffects,
      };
    }
    case "whisper.progress":
      return { ...state, whisper: data, ...noEffects };

    case "embedding.backfill.progress":
      // Carried raw; backfill.ts turns it into display state.
      return { ...state, embedding: data, ...noEffects };

    case "dailylog.updated":
      return {
        ...state,
        timelineKey: state.timelineKey + 1,
        ...noEffects,
        toast:
          data.kind === "daily-report" && typeof data.day === "string"
            ? `Daily report for ${data.day} is ready`
            : null,
      };

    default:
      return { ...state, ...noEffects };
  }
}