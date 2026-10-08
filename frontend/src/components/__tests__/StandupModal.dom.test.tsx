/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import StandupModal from "../StandupModal";
import { api } from "../../api";
import type { StandupOut } from "../../types";

vi.mock("../../api", () => ({
  api: {
    standup: vi.fn(),
    generateStandup: vi.fn(),
    saveStandupAsNote: vi.fn(),
  },
}));

describe("StandupModal (#69)", () => {
  const mockStandup: StandupOut = {
    day: "2026-10-08",
    previous_day: "2026-10-07",
    standup_md: "# Standup — 2026-10-08\n\n## Yesterday (2026-10-07)\n- Completed: **Task A**\n\n## Today\n- `[P1]` **Task B**\n\n## Blockers\n- None.",
    model: "fallback",
    yesterday_tasks: [
      {
        id: "t1",
        note_id: "n1",
        text: "Task A",
        done: true,
        priority: "P2",
        due_date: null,
        repo: null,
        created_at: "2026-10-07T10:00:00Z",
        completed_at: "2026-10-07T15:00:00Z",
      },
    ],
    today_tasks: [
      {
        id: "t2",
        note_id: "n1",
        text: "Task B",
        done: false,
        priority: "P1",
        due_date: "2026-10-08",
        repo: null,
        created_at: "2026-10-08T09:00:00Z",
        completed_at: null,
      },
    ],
    blockers: [],
  };

  beforeEach(() => {
    vi.mocked(api.standup).mockResolvedValue(mockStandup);
    vi.mocked(api.generateStandup).mockResolvedValue(mockStandup);
    vi.mocked(api.saveStandupAsNote).mockResolvedValue({
      ok: true,
      note: {
        id: "note-standup",
        type: "text",
        title: "Daily Standup — 2026-10-08",
        summary: "",
        raw_text: mockStandup.standup_md,
        tags: ["standup", "daily"],
        action_items: [],
        source: { type: "standup", day: "2026-10-08" },
        audio_path: null,
        status: "done",
        error: null,
        pinned: false,
        archived: false,
        created_at: "2026-10-08T10:00:00Z",
        updated_at: "2026-10-08T10:00:00Z",
        processed_at: null,
      },
    });

    Object.defineProperty(navigator, "clipboard", {
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders standup details and metric pills", async () => {
    render(<StandupModal isOpen={true} onClose={() => {}} onToast={() => {}} day="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByText("Daily Standup")).toBeDefined();
    });

    expect(screen.getByText(/1 completed/i)).toBeDefined();
    expect(screen.getByText(/1 planned/i)).toBeDefined();
    expect(screen.getByText(/0 open/i)).toBeDefined();
    expect(screen.getByText(/Task A/)).toBeDefined();
    expect(screen.getByText(/Task B/)).toBeDefined();
  });

  it("copies standup markdown to clipboard", async () => {
    const onToast = vi.fn();
    render(<StandupModal isOpen={true} onClose={() => {}} onToast={onToast} day="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByText("Copy")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Copy"));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(mockStandup.standup_md);
      expect(onToast).toHaveBeenCalledWith("Standup copied to clipboard");
    });
  });

  it("saves standup as a markdown note", async () => {
    const onToast = vi.fn();
    render(<StandupModal isOpen={true} onClose={() => {}} onToast={onToast} day="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByText("Save Note")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Save Note"));

    await waitFor(() => {
      expect(api.saveStandupAsNote).toHaveBeenCalledWith("2026-10-08", mockStandup.standup_md);
      expect(onToast).toHaveBeenCalledWith("Saved standup as note");
    });
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    render(<StandupModal isOpen={true} onClose={onClose} onToast={() => {}} day="2026-10-08" />);

    await waitFor(() => {
      expect(screen.getByLabelText("Close standup dialog")).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText("Close standup dialog"));
    expect(onClose).toHaveBeenCalled();
  });
});
