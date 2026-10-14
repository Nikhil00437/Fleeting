// #187: reconnect the server-event stream with backoff we control.
//
// `EventSource` does reconnect on its own, but on the browser's schedule: no
// cap, no jitter, and a connection that goes half-open (no error, no data) can
// sit there indefinitely while the inbox quietly goes stale. Surfacing
// `onerror` tells the user something broke; it does not fix it.
//
// So the native retry is turned off by closing the socket ourselves and
// reconnecting on our own terms:
//
// - **Exponential backoff**, capped. Uncapped, a backend that is down for an
//   hour produces a reconnect every few seconds for an hour.
// - **Jitter.** One laptop running three tabs that all reconnect on the same
//   tick is a thundering herd aimed at a server that is already struggling.
// - **A watchdog.** Any connection that opens and then says nothing for
//   `WATCHDOG_MS` is presumed dead, because half-open is the failure this
//   cannot otherwise detect.
// - **Reset on open.** A connection that worked earns attempt 0 again, so one
//   blip does not leave the next one waiting 30 seconds.
//
// The policy is a module rather than a `useEffect` body because that is the
// only way to test timing without a browser — see AGENTS.md.

/** Minimum reconnect delay. */
export const BACKOFF_BASE_MS = 500;
/** Ceiling on the backoff, so recovery after a restart is prompt. */
export const BACKOFF_MAX_MS = 30_000;
/** Silence after which an open connection is presumed half-open. */
export const WATCHDOG_MS = 45_000;

export interface EventSourceLike {
  close(): void;
  onopen: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
}

export interface ConnectorOptions<T> {
  create: () => EventSourceLike;
  onMessage: (data: T) => void;
  onOpen?: () => void;
  onDown?: (attempt: number, retryInMs: number) => void;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
  random?: () => number;
}

/**
 * Delay before reconnect `attempt` (0-based).
 *
 * Jitter is a multiplier in `[0.5, 1)`, not an additive range: additive jitter
 * added to a capped delay is frequently larger than the delay itself, which
 * produces the opposite of spreading load out.
 */
export function backoffDelay(
  attempt: number,
  random: () => number = Math.random,
  base: number = BACKOFF_BASE_MS,
  max: number = BACKOFF_MAX_MS,
): number {
  const exponential = Math.min(max, base * 2 ** Math.max(0, attempt));
  return Math.round(exponential * (0.5 + random() * 0.5));
}

export interface Connector {
  /** Stop for good. No reconnect fires after this, even one already scheduled. */
  close(): void;
  /** Consecutive failures since the last successful open. */
  attempt(): number;
  /** Notified on every open, including the first. */
  isOpen(): boolean;
}

/**
 * Hold one SSE connection open, reconnecting on our own schedule.
 *
 * `close()` cancels the pending reconnect as well as the socket: the usual bug
 * here is unmounting while a retry is scheduled, and firing it reopens a
 * connection the component no longer owns.
 */
export function connectStream<T>(options: ConnectorOptions<T>): Connector {
  const {
    create,
    onMessage,
    onOpen,
    onDown,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    random = Math.random,
  } = options;

  let source: EventSourceLike | null = null;
  let retry: unknown = null;
  let watchdog: unknown = null;
  let failures = 0;
  let open = false;
  let stopped = false;

  const armWatchdog = () => {
    if (watchdog !== null) clearTimer(watchdog);
    watchdog = setTimer(() => {
      watchdog = null;
      // Half-open: the socket is alive and silent. Force a reconnect rather
      // than waiting for an error that may never come.
      teardown();
      schedule();
    }, WATCHDOG_MS);
  };

  const teardown = () => {
    if (watchdog !== null) {
      clearTimer(watchdog);
      watchdog = null;
    }
    if (source) {
      source.onopen = null;
      source.onerror = null;
      source.onmessage = null;
      source.close();
      source = null;
    }
  };

  const schedule = () => {
    const delay = backoffDelay(failures, random);
    if (open) open = false;
    onDown?.(failures, delay);
    retry = setTimer(() => {
      retry = null;
      connect();
    }, delay);
  };

  const connect = () => {
    if (stopped) return;
    try {
      source = create();
    } catch {
      // A constructor that throws must not take the app down; it is a
      // connection problem like any other.
      schedule();
      return;
    }
    source.onopen = () => {
      failures = 0;
      open = true;
      onOpen?.();
      armWatchdog();
    };
    source.onmessage = (ev: { data: string }) => {
      // Any traffic at all proves the connection is alive, so the watchdog
      // restarts — including messages that fail to parse further up.
      armWatchdog();
      let parsed: T;
      try {
        parsed = JSON.parse(ev.data) as T;
      } catch {
        return; // malformed frame — ignore, exactly as before
      }
      onMessage(parsed);
    };
    source.onerror = () => {
      if (stopped) return;
      teardown();
      // Schedule *before* counting, so the first failure waits the base delay
      // rather than twice it: `failures` is "how many have already happened",
      // not "how many including this one". Incrementing first doubles every
      // delay and makes a single blip feel like a slow start.
      schedule();
      failures += 1;
    };
  };

  connect();
  return {
    close() {
      stopped = true;
      if (retry !== null) {
        clearTimer(retry);
        retry = null;
      }
      teardown();
      open = false;
    },
    attempt: () => failures,
    isOpen: () => open,
  };
}