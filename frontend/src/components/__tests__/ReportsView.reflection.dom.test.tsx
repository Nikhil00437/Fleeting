// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import ReportsView from "../ReportsView";
import { api } from "../../api";
import type { DailyLog, Note } from "../../types";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-08T12:00:00Z"));
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
  summary_md: "# Daily Digest — 2026-10-08\n\nDaily report content.",
  edited_body: null,
  edited: 0,
  model: "ollama",
  created_at: "2026-10-08T12:00:00Z",
};

describe("ReportsView daily reflection (#347)", () => {
  it("renders reflection prompt and allows saving as a linked note", async () => {
    const onToast = vi.fn();
    vi.spyOn(api, "dailyLog").mockResolvedValue({ ...mockLog });
    vi.spyOn(api, "dailyReflection").mockResolvedValue({
      day: "2026-10-08",
      prompts: [
        "What gave you momentum today?",
        "Where did unexpected friction pull you off track?",
      ],
      note: null,
    });
    const saveSpy = vi.spyOn(api, "saveDailyReflection").mockResolvedValue({
      id: "note-123",
      title: "Daily Reflection — 2026-10-08",
      raw_text: "> **Prompt**: What gave you momentum today?\n\nHigh energy on deep work.",
      tags: ["reflection", "daily", "daily/2026-10-08"],
    } as unknown as Note);
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
      expect(screen.getByText(/Daily Reflection/i)).toBeDefined();
      expect(screen.getByText(/What gave you momentum today\?/i)).toBeDefined();
    });

    // Shuffle prompt
    const shuffleBtn = screen.getByText("Shuffle");
    fireEvent.click(shuffleBtn);
    expect(screen.getByText(/Where did unexpected friction pull you off track\?/i)).toBeDefined();

    // Type response
    const textarea = screen.getByLabelText("Reflection response");
    fireEvent.change(textarea, { target: { value: "High energy on deep work." } });

    // Save
    const saveBtn = screen.getByText("Save Reflection as Note");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledWith(
        "2026-10-08",
        "Where did unexpected friction pull you off track?",
        "High energy on deep work."
      );
      expect(onToast).toHaveBeenCalledWith("reflection saved as linked note");
      expect(screen.getByText("Linked Note Saved")).toBeDefined();
    });
  });
});
