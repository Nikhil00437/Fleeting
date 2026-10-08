// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReportsView from "../ReportsView";
import { api } from "../../api";
import type { DailyLog } from "../../types";

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

const mockLog: DailyLog = {
  day: "2026-10-08",
  summary_md: "# Daily Digest — 2026-10-08\n\nAI generated text.",
  edited_body: null,
  edited: 0,
  model: "ollama",
  created_at: "2026-10-08T12:00:00Z",
};

describe("ReportsView editable reports (#72)", () => {
  it("opens the markdown editor and allows saving edits", async () => {
    const onToast = vi.fn();
    vi.spyOn(api, "dailyLog").mockResolvedValue({ ...mockLog });
    const editSpy = vi.spyOn(api, "editDailyLog").mockResolvedValue({ ok: true, edited: 1, body: "My custom words." });
    vi.spyOn(api, "weeklyLog").mockResolvedValue({
      week: "2026-10-05",
      this_week: "2026-10-05",
      report: null,
      summary: { total_seconds: 0, days: [] } as any,
    });
    vi.spyOn(api, "orphans").mockResolvedValue({
      single_use_tags: [],
      untagged_notes: [],
      unlinked_tasks: [],
    });

    render(<ReportsView onToast={onToast} refreshKey={0} />);

    // Wait for the report to render
    await waitFor(() => {
      expect(screen.getByText(/AI generated text/i)).toBeDefined();
    });

    // Click edit button
    const editBtn = screen.getByLabelText("Edit report");
    fireEvent.click(editBtn);

    // Textarea should appear with the raw report text
    const textarea = screen.getByPlaceholderText("Write your digest...") as HTMLTextAreaElement;
    expect(textarea.value).toContain("AI generated text.");

    // Type human edits
    fireEvent.change(textarea, { target: { value: "My custom words." } });

    // Save
    const saveBtn = screen.getByText("Save edits");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(editSpy).toHaveBeenCalledWith("2026-10-08", "My custom words.");
      expect(onToast).toHaveBeenCalledWith("report edits saved");
    });

    // "Edited" badge should now be visible
    expect(screen.getByText("Edited")).toBeDefined();
  });

  it("allows reverting an edited report back to the AI version", async () => {
    const onToast = vi.fn();
    vi.spyOn(api, "dailyLog").mockResolvedValue({
      ...mockLog,
      edited: 1,
      edited_body: "My custom words.",
    });
    const clearSpy = vi.spyOn(api, "clearDailyLogEdit").mockResolvedValue(undefined);
    vi.spyOn(api, "weeklyLog").mockResolvedValue({
      week: "2026-10-05",
      this_week: "2026-10-05",
      report: null,
      summary: { total_seconds: 0, days: [] } as any,
    });
    vi.spyOn(api, "orphans").mockResolvedValue({
      single_use_tags: [],
      untagged_notes: [],
      unlinked_tasks: [],
    });

    render(<ReportsView onToast={onToast} refreshKey={0} />);

    await waitFor(() => {
      expect(screen.getByText("Edited")).toBeDefined();
    });

    // Click edit button
    const editBtn = screen.getByLabelText("Edit report");
    fireEvent.click(editBtn);

    // Revert button should be present
    const revertBtn = screen.getByText("Revert to AI version");
    fireEvent.click(revertBtn);

    await waitFor(() => {
      expect(clearSpy).toHaveBeenCalledWith("2026-10-08");
      expect(onToast).toHaveBeenCalledWith("reverted to original AI summary");
    });
  });
});
