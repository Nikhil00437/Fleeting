import { describe, expect, it } from "vitest";
import { applyServerEvent, emptyServerState, type ServerState } from "../serverEvents";

const base = (): ServerState => ({
  liveApp: null,
  whisper: null,
  timelineKey: 0,
  tasksKey: 0,
  notes: [],
});

describe("note events", () => {
  it("adds a created note", () => {
    const s = applyServerEvent(base(), {
      type: "note.created",
      data: { id: "n1", title: "a" },
    });
    expect(s.notes.map((n) => n.id)).toEqual(["n1"]);
  });

  it("updates an existing note in place rather than duplicating it", () => {
    let s = applyServerEvent(base(), { type: "note.created", data: { id: "n1", title: "a" } });
    s = applyServerEvent(s, { type: "note.updated", data: { id: "n1", title: "b" } });
    expect(s.notes).toHaveLength(1);
    expect(s.notes[0].title).toBe("b");
  });

  it("removes a deleted note", () => {
    let s = applyServerEvent(base(), { type: "note.created", data: { id: "n1" } });
    s = applyServerEvent(base(), { type: "note.created", data: { id: "n2" } });
    s.notes = [s.notes[0]];
    s = applyServerEvent(s, { type: "note.deleted", data: { id: "n1" } });
    expect(s.notes.map((n) => n.id)).toEqual(["n2"]);
  });

  it("reports whether a stats refresh is needed", () => {
    const s = applyServerEvent(base(), {
      type: "note.updated",
      data: { id: "n1", status: "done" },
    });
    expect(s.refreshStats).toBe(true);
  });

  it("does not request a stats refresh for a still-pending note", () => {
    const s = applyServerEvent(base(), {
      type: "note.updated",
      data: { id: "n1", status: "processing" },
    });
    expect(s.refreshStats).toBe(false);
  });
});

describe("task events — the bug this fixes", () => {
  it("bumps the task key on task.created", () => {
    const s = applyServerEvent(base(), { type: "task.created", data: { id: "t1" } });
    expect(s.tasksKey).toBe(1);
  });

  it("bumps the task key on task.updated", () => {
    const s = applyServerEvent(base(), { type: "task.updated", data: { id: "t1" } });
    expect(s.tasksKey).toBe(1);
  });

  it("bumps the task key on task.deleted", () => {
    const s = applyServerEvent(base(), { type: "task.deleted", data: { id: "t1" } });
    expect(s.tasksKey).toBe(1);
  });

  it("bumps once per event, not per task in a payload", () => {
    let s = base();
    s = applyServerEvent(s, { type: "task.created", data: { id: "t1" } });
    s = applyServerEvent(s, { type: "task.created", data: { id: "t2" } });
    expect(s.tasksKey).toBe(2);
  });
});

describe("other event types", () => {
  it("tracks the live activity app", () => {
    const s = applyServerEvent(base(), {
      type: "activity.live",
      data: { session: { app_class: "code" } },
    });
    expect(s.liveApp).toBe("code");
  });

  it("clears the live app when the session ends", () => {
    let s = applyServerEvent(base(), {
      type: "activity.live",
      data: { session: { app_class: "code" } },
    });
    s = applyServerEvent(s, { type: "activity.live", data: { session: null } });
    expect(s.liveApp).toBeNull();
  });

  it("tolerates a missing session key", () => {
    const s = applyServerEvent(base(), { type: "activity.live", data: {} });
    expect(s.liveApp).toBeNull();
  });

  it("carries whisper progress", () => {
    const s = applyServerEvent(base(), {
      type: "whisper.progress",
      data: { status: "downloading", percent: 40 },
    });
    expect(s.whisper).toEqual({ status: "downloading", percent: 40 });
  });

  it("bumps the timeline key on a daily log", () => {
    const s = applyServerEvent(base(), {
      type: "dailylog.updated",
      data: { kind: "daily-report", day: "2026-10-04" },
    });
    expect(s.timelineKey).toBe(1);
    expect(s.toast).toBe("Daily report for 2026-10-04 is ready");
  });

  it("bumps the timeline without a toast for other kinds", () => {
    const s = applyServerEvent(base(), { type: "dailylog.updated", data: { kind: "other" } });
    expect(s.timelineKey).toBe(1);
    expect(s.toast).toBeNull();
  });

  it("ignores an unknown event type", () => {
    const before = base();
    const after = applyServerEvent(before, { type: "who.knows", data: { x: 1 } });
    // Effects are always present on the result; the state fields must not move.
    expect(after.notes).toEqual(before.notes);
    expect(after.tasksKey).toBe(before.tasksKey);
    expect(after.timelineKey).toBe(before.timelineKey);
    expect(after.liveApp).toBe(before.liveApp);
    expect(after.whisper).toBe(before.whisper);
    expect(after.refreshStats).toBe(false);
    expect(after.toast).toBeNull();
  });

  it("never throws on a malformed payload", () => {
    for (const bad of [{}, { type: "note.created" }, { type: "activity.live", data: 5 }]) {
      expect(() => applyServerEvent(base(), bad)).not.toThrow();
    }
  });

  it("never mutates the input state", () => {
    const before = base();
    const snapshot = JSON.stringify(before);
    applyServerEvent(before, { type: "note.created", data: { id: "n1" } });
    expect(JSON.stringify(before)).toBe(snapshot);
  });
});

describe("emptyServerState", () => {
  it("starts at zero and null", () => {
    const s = emptyServerState();
    expect(s).toEqual({
      liveApp: null,
      whisper: null,
      timelineKey: 0,
      tasksKey: 0,
      notes: [],
    });
  });
});