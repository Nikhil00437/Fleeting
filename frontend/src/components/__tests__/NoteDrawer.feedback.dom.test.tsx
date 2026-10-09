/**
 * #255 the enrichment thumb actually sends a verdict and reflects the new one.
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import NoteDrawer from "../NoteDrawer";
import { api } from "../../api";
import type { Note } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function note(overrides: Partial<Note> = {}): Note {
  return {
    id: "n1",
    type: "text",
    title: "Router notes",
    summary: "s",
    raw_text: "The router runs OpenWrt.",
    tags: ["homelab"],
    action_items: [],
    source: { enrichment: "local-llm" },
    audio_path: null,
    status: "done",
    error: null,
    pinned: false,
    archived: false,
    created_at: "2026-10-09T10:00:00Z",
    updated_at: "2026-10-09T10:00:00Z",
    processed_at: "2026-10-09T10:00:00Z",
    enrich_confidence: 0.91,
    enrich_feedback: 0,
    ...overrides,
  };
}

function renderDrawer(n: Note, onUpdate = vi.fn()) {
  render(
    <NoteDrawer
      note={n}
      onClose={() => {}}
      onUpdate={onUpdate}
      onToast={() => {}}
    />,
  );
  return onUpdate;
}

describe("NoteDrawer enrichment confidence and feedback", () => {
  it("shows the model's reported confidence", () => {
    renderDrawer(note());
    expect(screen.getByTestId("enrich-confidence").textContent).toContain("91%");
  });

  it("shows no confidence at all for heuristic enrichment", () => {
    // Deterministic extraction is not uncertain, so there is nothing to report.
    renderDrawer(note({ enrich_confidence: null, source: { enrichment: "heuristic" } }));
    expect(screen.queryByTestId("enrich-confidence")).toBeNull();
  });

  it("offers no thumb on sensitive notes", () => {
    // #26: sensitive notes are never enriched by a model, so rating that
    // enrichment would be rating a heuristic as if a model had produced it.
    renderDrawer(
      note({ enrich_confidence: null, source: { enrichment: "heuristic-sensitive" } }),
    );
    expect(screen.queryByTestId("enrich-feedback")).toBeNull();
  });

  it("records a thumbs-up", async () => {
    const spy = vi.spyOn(api, "rateEnrichment").mockResolvedValue(note({ enrich_feedback: 1 }));
    renderDrawer(note());

    fireEvent.click(screen.getByLabelText("Good enrichment"));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("n1", 1));
  });

  it("clears the verdict when the same thumb is clicked twice", async () => {
    const spy = vi.spyOn(api, "rateEnrichment").mockResolvedValue(note({ enrich_feedback: 0 }));
    renderDrawer(note({ enrich_feedback: 1 }));

    fireEvent.click(screen.getByLabelText("Good enrichment"));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("n1", 0));
  });

  it("marks the active thumb as pressed for screen readers", () => {
    renderDrawer(note({ enrich_feedback: -1 }));
    expect(screen.getByLabelText("Bad enrichment").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByLabelText("Good enrichment").getAttribute("aria-pressed")).toBe("false");
  });
});
