// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import PrivateBadge from "../PrivateBadge";
import { api } from "../../api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const inMinutes = (m: number) => new Date(Date.now() + m * 60000).toISOString();

function setup(state: { active: boolean; until: string | null }, onToast = vi.fn()) {
  vi.spyOn(api, "privateState").mockResolvedValue(state);
  render(<PrivateBadge onToast={onToast} />);
  return { onToast };
}

describe("PrivateBadge (#65)", () => {
  it("shows nothing when private mode is off", async () => {
    setup({ active: false, until: null });
    await waitFor(() => expect(api.privateState).toHaveBeenCalled());
    expect(screen.queryByLabelText("Private mode is on")).toBeNull();
  });

  it("says how much private time is left", async () => {
    setup({ active: true, until: inMinutes(45) });
    expect(await screen.findByText(/45 min left/)).toBeTruthy();
  });

  it("extends the window from the badge", async () => {
    const { onToast } = setup({ active: true, until: inMinutes(5) });
    const start = vi.spyOn(api, "startPrivate").mockResolvedValue({ active: true, until: inMinutes(35) });

    fireEvent.click(await screen.findByText("+30m"));
    await waitFor(() => expect(start).toHaveBeenCalledWith(30));
    expect(onToast).toHaveBeenCalledWith("Tracking paused for 30 minutes");
  });

  it("resumes early", async () => {
    const { onToast } = setup({ active: true, until: inMinutes(5) });
    const stop = vi.spyOn(api, "stopPrivate").mockResolvedValue(undefined);
    // the badge re-reads the state after resuming; this spy answers that call
    vi.spyOn(api, "privateState").mockResolvedValue({ active: false, until: null });

    fireEvent.click(await screen.findByText("Resume"));
    await waitFor(() => expect(stop).toHaveBeenCalled());
    expect(onToast).toHaveBeenCalledWith("Tracking resumed");
    await waitFor(() => expect(screen.queryByLabelText("Private mode is on")).toBeNull());
  });

  it("reports a failed resume and keeps the badge up", async () => {
    const { onToast } = setup({ active: true, until: inMinutes(5) });
    vi.spyOn(api, "stopPrivate").mockRejectedValue(new Error("not running"));

    fireEvent.click(await screen.findByText("Resume"));
    await waitFor(() => expect(onToast).toHaveBeenCalledWith("not running", "err"));
    expect(screen.getByLabelText("Private mode is on")).toBeTruthy();
  });
});