// #187: the reconnect policy.
//
// Timing tests with real timers are flaky by construction, so the timer
// functions are injected and driven by hand. What is under test is the policy —
// does it back off, does it reset, does it notice a dead connection — not the
// browser's timer.

import { describe, expect, it, vi } from "vitest";

import {
  BACKOFF_MAX_MS,
  WATCHDOG_MS,
  backoffDelay,
  connectStream,
  type EventSourceLike,
} from "./sseReconnect";

/** How many watchdogs are armed right now — a cancelled one has `ms: -1`. */
function liveWatchdogs(h: { timers: { ms: number }[] }): number {
  return h.timers.filter((t) => t.ms === WATCHDOG_MS).length;
}

/** How many watchdogs have *ever* been armed, cancelled or not. */
function armedWatchdogs(h: { timers: { ms: number }[] }): number {
  return h.timers.filter((t) => t.ms === WATCHDOG_MS || t.ms === -1).length;
}

/** A controllable stand-in for `EventSource`. */
class FakeSource implements EventSourceLike {
  static made: FakeSource[] = [];
  onopen: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  closed = false;

  constructor() {
    FakeSource.made.push(this);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.({});
  }
  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
  raw(data: string) {
    this.onmessage?.({ data });
  }
  fail() {
    this.onerror?.({});
  }
}

function harness(overrides: Partial<Parameters<typeof connectStream>[0]> = {}) {
  FakeSource.made = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const onDown = vi.fn();
  const onOpen = vi.fn();
  const onMessage = vi.fn();
  const stream = connectStream<{ type?: string }>({
    create: () => new FakeSource(),
    onMessage,
    onOpen,
    onDown,
    setTimer: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length - 1;
    },
    clearTimer: (handle) => {
      timers[handle as number] = { fn: () => {}, ms: -1 };
    },
    random: () => 0.5, // fixed jitter: predictable delay, jitter tested separately
    ...overrides,
  });
  const fire = () => {
    const due = timers.filter((t) => t.ms >= 0);
    timers.length = 0;
    due.forEach((t) => t.fn());
  };
  return { stream, timers, fire, onDown, onOpen, onMessage, source: () => FakeSource.made.at(-1)! };
}

// ---- backoff ---------------------------------------------------------------

describe("backoffDelay", () => {
  it("grows with the attempt", () => {
    const at = (n: number) => backoffDelay(n, () => 0.5);
    expect(at(0)).toBeLessThan(at(1));
    expect(at(1)).toBeLessThan(at(2));
  });

  it("is capped", () => {
    expect(backoffDelay(40, () => 0.999)).toBeLessThanOrEqual(BACKOFF_MAX_MS);
  });

  it("jitters, so tabs do not reconnect in lockstep", () => {
    const delays = new Set(
      Array.from({ length: 20 }, () => backoffDelay(3, () => Math.random())),
    );
    expect(delays.size).toBeGreaterThan(1);
  });

  it("treats a negative attempt as the first", () => {
    expect(backoffDelay(-5, () => 0.5)).toBe(backoffDelay(0, () => 0.5));
  });

  it("never exceeds the cap, even at the jitter maximum", () => {
    // Additive jitter on a capped delay is routinely larger than the delay
    // itself, which spreads load in exactly the wrong direction.
    expect(backoffDelay(40, () => 0.999)).toBeLessThanOrEqual(BACKOFF_MAX_MS);
    expect(backoffDelay(10, () => 0)).toBeGreaterThanOrEqual(BACKOFF_MAX_MS / 2);
  });
});

// ---- reconnecting ----------------------------------------------------------

describe("connectStream", () => {
  it("opens the first connection without waiting", () => {
    const h = harness();
    expect(FakeSource.made).toHaveLength(1);
    h.source().open();
    expect(h.onOpen).toHaveBeenCalledOnce();
    expect(h.stream.isOpen()).toBe(true);
  });

  it("reconnects after an error", () => {
    const h = harness();
    h.source().open();
    h.source().fail();
    h.fire();
    expect(FakeSource.made).toHaveLength(2);
  });

  it("backs off rather than hammering", () => {
    const h = harness();
    h.source().fail();
    const first = h.onDown.mock.calls[0][1];
    h.fire();
    h.source().fail();
    const second = h.onDown.mock.calls[1][1];
    expect(second).toBeGreaterThan(first);
  });

  it("resets the backoff once a connection works", () => {
    const h = harness();
    h.source().fail();
    h.fire();
    h.source().fail();
    expect(h.stream.attempt()).toBe(2);

    // Fire again first: a socket that has errored is muted, so opening the
    // stale one would be testing that it correctly does nothing.
    h.fire();
    h.source().open();
    expect(h.stream.attempt()).toBe(0);

    h.source().fail();
    expect(h.onDown.mock.calls.at(-1)![1]).toBe(backoffDelay(0, () => 0.5));
  });

  it("closes the old socket before opening a new one", () => {
    // Two live connections means duplicate events applied twice.
    const h = harness();
    h.source().open();
    h.source().fail();
    expect(h.source().closed).toBe(true);
    h.fire();
    expect(FakeSource.made).toHaveLength(2);
  });

  it("stops a stale socket from delivering after an error", () => {
    const h = harness();
    h.source().open();
    const stale = FakeSource.made[0];
    stale.fail();
    stale.message({ type: "note.created" });
    expect(h.onMessage).not.toHaveBeenCalled();
  });

  it("reports being down while retrying", () => {
    const h = harness();
    h.source().open();
    h.source().fail();
    expect(h.stream.isOpen()).toBe(false);
  });
});

// ---- the watchdog ----------------------------------------------------------

describe("watchdog", () => {
  it("reconnects a connection that went silent", () => {
    // The half-open case: no error event, no data, an inbox that quietly goes
    // stale. Nothing else in this file detects it.
    const h = harness();
    h.source().open();
    expect(liveWatchdogs(h)).toBe(1);
    h.fire(); // the watchdog fires and schedules a retry
    expect(h.onDown).toHaveBeenCalledOnce();
    h.fire(); // the retry opens the replacement
    expect(FakeSource.made.length).toBeGreaterThan(1);
  });

  it("is reset by traffic", () => {
    const h = harness();
    h.source().open();
    h.source().message({ type: "note.created" });
    // Re-armed, not stacked: a second watchdog is armed, and exactly one is
    // live. Asserting only the live count would pass even if traffic did
    // nothing, because the original would still be armed.
    expect(armedWatchdogs(h)).toBe(2);
    expect(liveWatchdogs(h)).toBe(1);
    expect(h.onMessage).toHaveBeenCalledOnce();
  });

  it("counts even a malformed frame as proof of life", () => {
    // Otherwise one unparseable frame disarms the watchdog for 45s.
    const h = harness();
    h.source().open();
    h.source().raw("{ not json");
    expect(armedWatchdogs(h)).toBe(2);
    expect(liveWatchdogs(h)).toBe(1);
    expect(h.onMessage).not.toHaveBeenCalled();
  });
});

// ---- teardown --------------------------------------------------------------

describe("close", () => {
  it("cancels a pending reconnect", () => {
    // The usual bug: unmounting with a retry scheduled, which reopens a
    // connection the component no longer owns.
    const h = harness();
    h.source().open();
    h.source().fail();
    h.stream.close();
    h.fire();
    expect(FakeSource.made).toHaveLength(1);
  });

  it("closes the socket", () => {
    const h = harness();
    h.source().open();
    const s = h.source();
    h.stream.close();
    expect(s.closed).toBe(true);
    expect(h.stream.isOpen()).toBe(false);
  });

  it("ignores an error that arrives after close", () => {
    const h = harness();
    h.source().open();
    const s = h.source();
    h.stream.close();
    expect(() => s.fail()).not.toThrow();
    // Fire the timers too: cancelling the pending retry is not enough, because
    // a late `onerror` schedules a *fresh* one. Without the stopped flag the
    // stream reopens after unmount.
    h.fire();
    expect(FakeSource.made).toHaveLength(1);
  });

  it("survives a constructor that throws", () => {
    let calls = 0;
    const h = harness({
      create: () => {
        calls += 1;
        if (calls === 1) throw new Error("backend not up");
        return new FakeSource();
      },
    });
    expect(() => h.fire()).not.toThrow();
    expect(FakeSource.made).toHaveLength(1);
  });
});