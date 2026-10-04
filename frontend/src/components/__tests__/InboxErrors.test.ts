import { describe, expect, it, vi } from "vitest";
import { runNoteAction, type ActionToast } from "../actionRunner";

const toast: ActionToast = vi.fn();

function makeApi(over: Partial<Record<string, unknown>> = {}) {
  return {
    deleteNote: vi.fn().mockResolvedValue(undefined),
    reprocess: vi.fn().mockResolvedValue({ id: "n1" }),
    stats: vi.fn().mockResolvedValue({} as never),
    toggleTask: vi.fn().mockResolvedValue(undefined),
    ...over,
  };
}

describe("note actions report failure", () => {
  it("reports a rejected delete instead of failing silently", async () => {
    const fakeApi = makeApi({
      deleteNote: vi.fn().mockRejectedValue(new Error("Database is locked")),
    });
    const result = await runNoteAction({
      api: fakeApi as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "Note deleted",
    });
    expect(result.ok).toBe(false);
    expect(toast).toHaveBeenCalledWith("Database is locked", "err");
  });

  it("runs the follow-up only on success", async () => {
    const onDone = vi.fn();
    const fakeApi = makeApi({
      deleteNote: vi.fn().mockRejectedValue(new Error("nope")),
    });
    const result = await runNoteAction({
      api: fakeApi as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "Note deleted",
      onDone,
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(result.ok).toBe(false);
  });

  it("still runs the follow-up when the action succeeds", async () => {
    const onDone = vi.fn();
    const result = await runNoteAction({
      api: makeApi() as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "Note deleted",
      onDone,
    });
    expect(onDone).toHaveBeenCalledOnce();
    expect(result.ok).toBe(true);
  });

  it("reports success when nothing fails", async () => {
    await runNoteAction({
      api: makeApi() as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "Note deleted",
    });
    expect(toast).toHaveBeenCalledWith("Note deleted", "ok");
  });

  it("never throws, whatever the action does", async () => {
    const fakeApi = makeApi({
      deleteNote: vi.fn().mockImplementation(() => {
        throw new Error("sync throw");
      }),
    });
    const result = await runNoteAction({
      api: fakeApi as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "ok",
    });
    expect(result.ok).toBe(false);
    expect(toast).toHaveBeenCalledWith("sync throw", "err");
  });

  it("falls back to a non-empty message for a rejected non-Error", async () => {
    const fakeApi = makeApi({
      deleteNote: vi.fn().mockRejectedValue({ detail: "weird" }),
    });
    await runNoteAction({
      api: fakeApi as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "ok",
    });
    const [msg, kind] = vi.mocked(toast).mock.calls[0] as [string, string];
    expect(kind).toBe("err");
    expect(msg.length).toBeGreaterThan(0);
  });

  it("does not swallow a follow-up failure silently", async () => {
    const fakeApi = makeApi();
    const onDone = vi.fn().mockImplementation(() => {
      throw new Error("onDone blew up");
    });
    await runNoteAction({
      api: fakeApi as never,
      toast,
      action: (a: { deleteNote: (id: string) => Promise<void> }) => a.deleteNote("n1"),
      success: "ok",
      onDone,
    });
    // The primary action still succeeded, but the follow-up error is reported.
    expect(toast).toHaveBeenCalledWith("onDone blew up", "err");
  });
});