/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import WhatShippedModal from "../WhatShippedModal";
import { api } from "../../api";
import type { WhatShippedOut } from "../../types";

vi.mock("../../api", () => ({
  api: {
    whatShipped: vi.fn(),
    saveWhatShippedAsNote: vi.fn(),
  },
}));

describe("WhatShippedModal (#166)", () => {
  const mockData: WhatShippedOut = {
    week_start: "2026-10-05",
    week_end: "2026-10-11",
    commits: [
      { repo: "fleeting", subject: "feat(reports): report playground", author: "dev", committed_at: "2026-10-07" },
    ],
    commits_by_repo: {
      fleeting: [
        { repo: "fleeting", subject: "feat(reports): report playground", author: "dev", committed_at: "2026-10-07" },
      ],
    },
    completed_tasks: [
      {
        id: "t1",
        note_id: "n1",
        text: "Optimize FTS queries",
        done: true,
        priority: "P1",
        repo: "fleeting",
        created_at: "2026-10-06T10:00:00Z",
        completed_at: "2026-10-07T12:00:00Z",
        due_date: null,
      },
    ],
    notes: [
      {
        id: "note-1",
        type: "text",
        title: "Architecture notes",
        tags: ["arch"],
        created_at: "2026-10-06T11:00:00Z",
      },
    ],
    markdown: "# What Shipped — Week of 2026-10-05\n\n## Git Commits (1)\n### fleeting\n- feat(reports): report playground\n\n## Completed Tasks (1)\n- [x] [P1] **Optimize FTS queries**",
    counts: {
      commits: 1,
      tasks: 1,
      notes: 1,
      total: 3,
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.whatShipped).mockResolvedValue(mockData);
    vi.mocked(api.saveWhatShippedAsNote).mockResolvedValue({
      ok: true,
      note: {
        id: "note-shipped",
        type: "text",
        title: "What Shipped — Week of 2026-10-05",
        summary: "",
        raw_text: mockData.markdown,
        tags: ["shipped", "weekly"],
        action_items: [],
        source: { type: "what_shipped" },
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

  it("renders what shipped counts and changelog", async () => {
    render(<WhatShippedModal isOpen={true} onClose={() => {}} onToast={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("What Shipped")).toBeDefined();
    });

    expect(screen.getByText("3 items shipped")).toBeDefined();
    expect(screen.getByText("1 commits")).toBeDefined();
    expect(screen.getByText("1 tasks closed")).toBeDefined();
    expect(screen.getByText("1 captures")).toBeDefined();
    expect(screen.getByText(/Optimize FTS queries/)).toBeDefined();
  });

  it("switches tabs to inspect individual commits, tasks, and captures", async () => {
    render(<WhatShippedModal isOpen={true} onClose={() => {}} onToast={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Commits \(1\)/i })).toBeDefined();
    });

    // Commits tab
    fireEvent.click(screen.getByRole("button", { name: /Commits \(1\)/i }));
    expect(screen.getByText("feat(reports): report playground")).toBeDefined();

    // Tasks tab
    fireEvent.click(screen.getByRole("button", { name: /Tasks \(1\)/i }));
    expect(screen.getByText("Optimize FTS queries")).toBeDefined();

    // Notes tab
    fireEvent.click(screen.getByRole("button", { name: /Captures \(1\)/i }));
    expect(screen.getByText("Architecture notes")).toBeDefined();
  });

  it("copies changelog and saves as note", async () => {
    const onToast = vi.fn();
    render(<WhatShippedModal isOpen={true} onClose={() => {}} onToast={onToast} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Copy Changelog/i })).toBeDefined();
    });

    // Copy to clipboard
    fireEvent.click(screen.getByRole("button", { name: /Copy Changelog/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(mockData.markdown);
      expect(onToast).toHaveBeenCalledWith("Weekly changelog copied to clipboard");
    });

    // Save as note
    fireEvent.click(screen.getByRole("button", { name: /Save as Note/i }));
    await waitFor(() => {
      expect(api.saveWhatShippedAsNote).toHaveBeenCalledWith("2026-10-05", mockData.markdown);
      expect(onToast).toHaveBeenCalledWith("Saved What Shipped changelog as note");
    });
  });
});
