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

const mockLogWithEvidence: DailyLog = {
  day: "2026-10-08",
  summary_md: "# Daily Digest — 2026-10-08\n\n## Shipped\n- Fixed backend bug in cursor.",
  edited_body: null,
  edited: 0,
  model: "ollama",
  created_at: "2026-10-08T12:00:00Z",
  evidence: [
    {
      section: "Shipped",
      text: "Fixed backend bug in cursor.",
      sessions: [
        {
          id: 10,
          app: "cursor",
          title: "fleeting/services/dailylog.py",
          seconds: 3600,
          start: "10:00",
          end: "11:00",
        },
      ],
      notes: [
        {
          id: "note-xyz",
          title: "Bugfix notes",
        },
      ],
      commits: [
        {
          repo: "fleeting",
          subject: "fix(reports): resolve bug",
        },
      ],
    },
  ],
};

describe("ReportsView Evidence Mode (#73, #350)", () => {
  it("toggles evidence mode and displays source citations", async () => {
    const onToast = vi.fn();
    vi.spyOn(api, "dailyLog").mockResolvedValue({ ...mockLogWithEvidence });
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
      expect(screen.getByText(/Fixed backend bug in cursor/i)).toBeDefined();
    });

    // Evidence button should be visible
    const evBtn = screen.getByLabelText("Toggle evidence mode");
    expect(evBtn).toBeDefined();

    // Toggle evidence mode on
    fireEvent.click(evBtn);

    // Explorer should appear
    await waitFor(() => {
      expect(screen.getByLabelText("Evidence Explorer")).toBeDefined();
    });

    // Check evidence contents
    expect(screen.getByText(/Evidence Mode — Source telemetry & notes/i)).toBeDefined();
    expect(screen.getByText(/1 citations/i)).toBeDefined();
    expect(screen.getAllByText(/cursor/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/\[10:00–11:00\]/i)).toBeDefined();
    expect(screen.getByText(/Bugfix notes/i)).toBeDefined();
    expect(screen.getByText(/fix\(reports\): resolve bug/i)).toBeDefined();
  });
});
