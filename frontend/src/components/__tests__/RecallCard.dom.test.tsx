// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import RecallCard from "../RecallCard";
import { api } from "../../api";
import type { Note } from "../../types";

const note = (id: string, title: string, created_at: string): Note =>
  ({ id, title, created_at }) as Note;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RecallCard", () => {
  it("surfaces the fetched note and its age", async () => {
    vi.spyOn(api, "recall").mockResolvedValue([
      note("a", "kota factory visit", new Date(Date.now() - 800 * 86400000).toISOString()),
    ]);
    render(<RecallCard onOpenNote={() => {}} />);

    expect(await screen.findByText("kota factory visit")).toBeTruthy();
    expect(screen.getByText(/years ago/)).toBeTruthy();
  });

  it("re-rolls the draw when the ⟳ button is pressed", async () => {
    const spy = vi.spyOn(api, "recall").mockResolvedValue([]);
    render(<RecallCard onOpenNote={() => {}} />);
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][0]).toBe("capsule");

    screen.getByLabelText("Show another resurfaced note").click();
    await waitFor(() => expect(spy.mock.calls.at(-1)?.[1]).toBe(1));
  });

  it("switches kind and says so when nothing is old enough", async () => {
    vi.spyOn(api, "recall").mockResolvedValue([]);
    render(<RecallCard onOpenNote={() => {}} />);
    await screen.findByText(/Nothing that far back yet/);

    screen.getByText("This day").click();
    await waitFor(() => expect(api.recall).toHaveBeenLastCalledWith("this_day", 0));
  });

  it("degrades to the empty state when the request fails", async () => {
    vi.spyOn(api, "recall").mockRejectedValue(new Error("offline"));
    render(<RecallCard onOpenNote={() => {}} />);
    expect(await screen.findByText(/Nothing that far back yet/)).toBeTruthy();
  });
});