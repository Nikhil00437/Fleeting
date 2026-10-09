/**
 * #453 preview + #112 trace list wired into the composer.
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import AssistantView from "../AssistantView";
import { api } from "../../api";
import type { ContextPreview, LlmTrace } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const trace: LlmTrace = {
  id: "t1",
  kind: "chat",
  queries: ["router firmware"],
  context: "=== Relevant Notes ===",
  tool_calls: [],
  tokens: null,
  ms: 42,
  at: "2026-10-09T10:00:00+00:00",
};

const preview: ContextPreview = {
  query: "router",
  context: "=== Relevant Notes ===\nOpenWrt",
  sources: [{ id: "n1", title: "Router notes", type: "text", kind: "note" }],
  context_used: { notes_count: 1, tasks_count: 0, logs_count: 0 },
  queries: ["router"],
};

function renderView() {
  return render(
    <AssistantView
      onOpenNote={() => {}}
      onToast={() => {}}
      initialSuggestions={[]}
      initialMessages={[]}
    />,
  );
}

describe("AssistantView trace and preview", () => {
  it("renders a collapsed trace row per recent call", async () => {
    vi.spyOn(api, "assistantTraces").mockResolvedValue([trace]);
    vi.spyOn(api, "assistantSuggestions").mockResolvedValue({ suggestions: [] });

    renderView();

    await waitFor(() => expect(screen.getByTestId("trace-toggle-t1")).toBeTruthy());
    // Collapsed by default: the summary is there, the context is not.
    expect(screen.getByTestId("trace-toggle-t1").textContent).toContain("1 search");
    expect(screen.queryByText("Relevant Notes")).toBeNull();
  });

  it("disables the preview button until there is a draft", async () => {
    vi.spyOn(api, "assistantTraces").mockResolvedValue([]);
    vi.spyOn(api, "assistantSuggestions").mockResolvedValue({ suggestions: [] });

    renderView();
    await waitFor(() => expect(screen.getByTestId("preview-context-btn")).toBeTruthy());
    expect((screen.getByTestId("preview-context-btn") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the preview after asking for one", async () => {
    vi.spyOn(api, "assistantTraces").mockResolvedValue([]);
    vi.spyOn(api, "assistantSuggestions").mockResolvedValue({ suggestions: [] });
    const spy = vi.spyOn(api, "assistantContextPreview").mockResolvedValue(preview);

    renderView();
    await waitFor(() => expect(screen.getByTestId("assistant-input")).toBeTruthy());

    fireEvent.change(screen.getByTestId("assistant-input"), { target: { value: "router" } });
    fireEvent.click(screen.getByTestId("preview-context-btn"));

    await waitFor(() => expect(spy).toHaveBeenCalledWith("router"));
    await waitFor(() => expect(screen.getByText("What the model will see")).toBeTruthy());
    expect(screen.getByText(/OpenWrt/)).toBeTruthy();
  });
});
