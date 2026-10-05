/**
 * @vitest-environment jsdom
 *
 * The SSE handler in App.tsx used to be an untestable if-chain inside a
 * useEffect. It is now a pure reducer (serverEvents.ts, covered by node-env
 * tests), but the *wiring* — that events reach the right setState, and that the
 * stream is torn down — was still unverified. That needs a DOM.
 *
 * The Probe below mirrors App.tsx's handler one-for-one; it is a test double
 * for the wiring, not a second implementation to maintain.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { useEffect, useRef, useState } from "react";
import {
  applyServerEvent,
  emptyServerState,
  type ServerNote,
  type ServerState,
} from "../serverEvents";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  emitRaw(data: string) {
    this.onmessage?.({ data });
  }

  close() {
    this.closed = true;
  }
}

interface Handle {
  emit: (payload: unknown) => void;
  emitRaw: (data: string) => void;
}

let handle: Handle | null = null;
/** Latest value of each tracked piece of state, read after each act(). */
const seen = {
  notes: [] as unknown[],
  tasksKey: -1,
  streamDown: null as boolean | null,
  embedding: null as Record<string, unknown> | null,
};

function Probe() {
  const [notes, setNotes] = useState<ServerNote[]>([]);
  const [tasksKey, setTasksKey] = useState(0);
  const [streamDown, setStreamDown] = useState(false);
  const [embedding, setEmbedding] = useState<Record<string, unknown> | null>(null);
  const serverState = useRef<ServerState>({
    ...emptyServerState(),
    notes: notes as ServerState["notes"],
  });

  useEffect(() => {
    const es = new FakeEventSource("/api/events");
    es.onmessage = (e) => {
      let parsed: { type?: string; data?: unknown };
      try {
        parsed = JSON.parse(e.data);
      } catch {
        return; // malformed frame
      }
      const before = serverState.current;
      const next = applyServerEvent({ ...before, notes }, parsed);
      serverState.current = next;
      if (next.notes !== before.notes) setNotes(next.notes);
      if (next.tasksKey !== before.tasksKey) setTasksKey(next.tasksKey);
      if (next.embedding !== before.embedding) setEmbedding(next.embedding);
    };
    es.onerror = () => setStreamDown(true);
    es.onopen = () => setStreamDown(false);
    handle = {
      emit: (p) => es.emit(p),
      emitRaw: (d) => es.emitRaw(d),
    };
    return () => es.close();
  }, [notes]);

  seen.notes = notes;
  seen.tasksKey = tasksKey;
  seen.streamDown = streamDown;
  seen.embedding = embedding;
  return <div>probe</div>;
}

beforeEach(() => {
  FakeEventSource.instances = [];
  handle = null;
  seen.notes = [];
  seen.tasksKey = -1;
  seen.streamDown = null;
  seen.embedding = null;
  vi.stubGlobal("EventSource", FakeEventSource as never);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  render(<Probe />);
}

describe("SSE wiring", () => {
  it("applies a task event — the bug where vault-watcher edits were invisible", () => {
    mount();
    expect(seen.tasksKey).toBe(0);
    act(() => handle!.emit({ type: "task.created", data: { id: "t1" } }));
    expect(seen.tasksKey).toBe(1);
  });

  it("adds and then updates a note without duplicating it", () => {
    mount();
    act(() => handle!.emit({ type: "note.created", data: { id: "n1", title: "a" } }));
    expect(seen.notes).toHaveLength(1);
    act(() => handle!.emit({ type: "note.updated", data: { id: "n1", title: "b" } }));
    expect(seen.notes).toHaveLength(1);
    expect((seen.notes[0] as { title: string }).title).toBe("b");
  });

  it("removes a deleted note", () => {
    mount();
    act(() => handle!.emit({ type: "note.created", data: { id: "n1" } }));
    act(() => handle!.emit({ type: "note.created", data: { id: "n2" } }));
    act(() => handle!.emit({ type: "note.deleted", data: { id: "n1" } }));
    expect(seen.notes.map((n) => (n as { id: string }).id)).toEqual(["n2"]);
  });

  it("surfaces a dropped stream and clears it on reconnect", () => {
    mount();
    act(() => FakeEventSource.instances[0].onerror?.());
    expect(seen.streamDown).toBe(true);
    act(() => FakeEventSource.instances[0].onopen?.());
    expect(seen.streamDown).toBe(false);
  });

  it("ignores a malformed frame instead of throwing", () => {
    mount();
    act(() => handle!.emitRaw("not json at all"));
    act(() => handle!.emitRaw("{broken"));
    expect(seen.tasksKey).toBe(0);
    expect(seen.notes).toHaveLength(0);
  });

  it("closes the stream on unmount", () => {
    mount();
    const es = FakeEventSource.instances[0];
    expect(es.closed).toBe(false);
    cleanup();
    expect(es.closed).toBe(true);
  });

  it("carries embedding backfill progress through", () => {
    mount();
    act(() =>
      handle!.emit({
        type: "embedding.backfill.progress",
        data: { done: 3, total: 10, started: true },
      }),
    );
    expect(seen.embedding).toMatchObject({ done: 3, total: 10 });
  });
});
