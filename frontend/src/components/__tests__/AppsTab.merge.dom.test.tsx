// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import AppsTab from "../settings/AppsTab";
import { api } from "../../api";
import type { AppRule } from "../../types";

const app = (app_class: string): AppRule =>
  ({ app_class, tracked: true, seconds: 600, sessions: 3, last_day: "2026-10-08" }) as AppRule;

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

function renderTab(onToast = vi.fn()) {
  const refresh = vi.fn();
  vi.spyOn(api, "appAliases").mockResolvedValue([]);
  render(
    <AppsTab apps={[app("firefox"), app("firefox-esr")]} toggleApp={async () => {}} bulkSetApps={async () => {}} refresh={refresh} onToast={onToast} />,
  );
  return { refresh, onToast };
}

describe("AppsTab rename & merge (#64)", () => {
  it("merges one app into another and refreshes the list", async () => {
    const { refresh, onToast } = renderTab();
    const setAlias = vi.spyOn(api, "setAppAlias").mockResolvedValue({ ok: true });

    fireEvent.change(screen.getByLabelText("App to rename"), { target: { value: "firefox-esr" } });
    fireEvent.change(screen.getByLabelText("Canonical app name"), { target: { value: "firefox" } });
    fireEvent.click(screen.getByText("Merge"));

    await waitFor(() => expect(setAlias).toHaveBeenCalledWith("firefox-esr", "firefox"));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(onToast).toHaveBeenCalledWith("Merged firefox-esr into firefox");
  });

  it("refuses a self-merge before touching the API", () => {
    const { onToast } = renderTab();
    const setAlias = vi.spyOn(api, "setAppAlias").mockResolvedValue({ ok: true });

    fireEvent.change(screen.getByLabelText("App to rename"), { target: { value: "firefox" } });
    fireEvent.change(screen.getByLabelText("Canonical app name"), { target: { value: "firefox" } });
    fireEvent.click(screen.getByText("Merge"));

    expect(setAlias).not.toHaveBeenCalled();
    expect(onToast).toHaveBeenCalledWith("Pick two different apps to merge", "err");
  });

  it("lists existing merges and can undo one", async () => {
    vi.spyOn(api, "appAliases").mockResolvedValue([
      { from_class: "firefox-esr", to_class: "firefox" },
    ]);
    const del = vi.spyOn(api, "deleteAppAlias").mockResolvedValue(undefined);
    render(
      <AppsTab apps={[app("firefox")]} toggleApp={async () => {}} bulkSetApps={async () => {}} />,
    );

    (await screen.findByLabelText("Undo merge of firefox-esr")).click();
    await waitFor(() => expect(del).toHaveBeenCalledWith("firefox-esr"));
  });

  it("surfaces a rejected merge instead of failing silently", async () => {
    const { onToast } = renderTab();
    vi.spyOn(api, "setAppAlias").mockRejectedValue(new Error("target is blocked"));

    fireEvent.change(screen.getByLabelText("App to rename"), { target: { value: "firefox-esr" } });
    fireEvent.change(screen.getByLabelText("Canonical app name"), { target: { value: "firefox" } });
    fireEvent.click(screen.getByText("Merge"));

    await waitFor(() => expect(onToast).toHaveBeenCalledWith("target is blocked", "err"));
  });
});