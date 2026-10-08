// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import SearchView from "../SearchView";
import { api } from "../../api";
import type { Note } from "../../types";

const note = (id: string, over: Partial<Note> = {}): Note =>
  ({
    id,
    type: "text",
    title: id,
    summary: "",
    raw_text: "",
    tags: [],
    action_items: [],
    source: {},
    audio_path: null,
    status: "done",
    error: null,
    pinned: false,
    archived: false,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    processed_at: null,
    ...over,
  }) as Note;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SearchView grouping", () => {
  it("offers day/tag/project only once there is more than one result", async () => {
    render(<SearchView notes={[note("a")]} onPin={() => {}} />);
    expect(screen.queryByLabelText("Group results by")).toBeNull();

    cleanup();
    render(
      <SearchView
        notes={[note("a"), note("b", { created_at: "2026-09-01T09:00:00Z" })]}
        onPin={() => {}}
      />,
    );
    expect(screen.getByLabelText("Group results by")).toBeTruthy();
  });

  it("buckets the cards under labelled headers when grouping is on", async () => {
    render(
      <SearchView
        notes={[
          note("a", { created_at: "2026-10-07T09:00:00Z" }),
          note("b", { created_at: "2026-10-07T11:00:00Z" }),
          note("c", { created_at: "2026-09-01T09:00:00Z" }),
        ]}
        onPin={() => {}}
      />,
    );
    screen.getByText("day").click();
    await waitFor(() => expect(screen.getByText(/Yesterday · 2/)).toBeTruthy());
    expect(screen.getByText(/Sep 1, 2026 · 1/)).toBeTruthy();
  });
});