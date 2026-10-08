// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import SessionEditor from "../SessionEditor";
import { api } from "../../api";
import type { ActivitySession } from "../../types";

const session = (over: Partial<ActivitySession> = {}): ActivitySession => ({
  id: 7,
  app_class: "kitty",
  title: "vim notes.md",
  first_seen: "2026-10-08T09:00:00",
  last_seen: "2026-10-08T09:30:00",
  seconds: 1800,
  day: "2026-10-08",
  ...over,
}) as ActivitySession;

beforeAll(() => {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const setup = (s = session()) => {
  const onToast = vi.fn();
  const onChanged = vi.fn();
  const onDone = vi.fn();
  render(
    <SessionEditor session={s} onToast={onToast} onChanged={onChanged} onDone={onDone} />,
  );
  return { onToast, onChanged, onDone };
};

describe("SessionEditor (#54)", () => {
  it("renames a session and stays open", async () => {
    const { onToast, onChanged, onDone } = setup();
    const relabel = vi.spyOn(api, "relabelSession").mockResolvedValue(session({ title: "hypr docs" }));

    fireEvent.change(screen.getByLabelText("Session label"), { target: { value: "hypr docs" } });
    fireEvent.click(screen.getByText("Save name"));

    await waitFor(() => expect(relabel).toHaveBeenCalledWith(7, "hypr docs"));
    expect(onToast).toHaveBeenCalledWith("Session renamed");
    expect(onChanged).toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled(); // keep editing after a rename
  });

  it("keeps Save name disabled until the label actually changes", () => {
    setup();
    expect(screen.getByText("Save name")).toHaveProperty("disabled", true);
  });

  it("prefills the split point with the midpoint", () => {
    setup();
    expect(screen.getByLabelText("Split at")).toHaveProperty("value", "2026-10-08T09:15");
  });

  it("splits at the chosen time and closes", async () => {
    const { onToast, onDone } = setup();
    const split = vi.spyOn(api, "splitSession").mockResolvedValue([session(), session({ id: 8 })]);

    fireEvent.change(screen.getByLabelText("Split at"), { target: { value: "2026-10-08T09:20" } });
    fireEvent.click(screen.getByText("Split"));

    await waitFor(() => expect(split).toHaveBeenCalledWith(7, "2026-10-08T09:20:00"));
    expect(onToast).toHaveBeenCalledWith("Session split");
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("deletes the session", async () => {
    const { onToast, onDone } = setup();
    const del = vi.spyOn(api, "deleteSession").mockResolvedValue(undefined);
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(del).toHaveBeenCalledWith(7));
    expect(onToast).toHaveBeenCalledWith("Session deleted");
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });

  it("reports a rejected edit instead of closing", async () => {
    const { onToast, onDone } = setup();
    vi.spyOn(api, "deleteSession").mockRejectedValue(new Error("session not found"));
    fireEvent.click(screen.getByText("Delete"));
    await waitFor(() => expect(onToast).toHaveBeenCalledWith("session not found", "err"));
    expect(onDone).not.toHaveBeenCalled();
  });
});