/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import PeriodicReviewModal from "../PeriodicReviewModal";
import { api } from "../../api";
import type { PeriodicReviewOut } from "../../types";

vi.mock("../../api", () => ({
  api: {
    periodicReview: vi.fn(),
    savePeriodicReviewAsNote: vi.fn(),
  },
}));

describe("PeriodicReviewModal (#70, #171, #172)", () => {
  const mockReview: PeriodicReviewOut = {
    kind: "month",
    period: "2026-10",
    start_date: "2026-10-01",
    end_date: "2026-10-31",
    title: "Monthly Review — 2026-10",
    review_md: "# Monthly Review — 2026-10\n\n## Month at a Glance\nLogged 42h focus.\n\n## Accomplishments\n- Shipped Review Generator.",
    model: "fallback",
    metrics: {
      total_seconds: 151200,
      active_days: 18,
      busiest_day: "2026-10-08",
      weekly_logs_count: 4,
      daily_logs_count: 18,
      completed_tasks_count: 24,
      top_apps: [{ app_class: "cursor", seconds: 100000 }],
    },
  };

  beforeEach(() => {
    vi.mocked(api.periodicReview).mockResolvedValue(mockReview);
    vi.mocked(api.savePeriodicReviewAsNote).mockResolvedValue({
      ok: true,
      note: {
        id: "note-rev",
        type: "text",
        title: "Monthly Review — 2026-10",
        summary: "",
        raw_text: mockReview.review_md,
        tags: ["review", "month", "month/2026-10"],
        action_items: [],
        source: { type: "periodic_review", kind: "month", period: "2026-10" },
        audio_path: null,
        status: "done",
        error: null,
        pinned: false,
        archived: false,
        created_at: "2026-10-31T00:00:00Z",
        updated_at: "2026-10-31T00:00:00Z",
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

  it("renders periodic review details and metric cards", async () => {
    render(<PeriodicReviewModal isOpen={true} onClose={() => {}} onToast={() => {}} />);

    await waitFor(() => {
      expect(screen.getAllByText("Monthly Review — 2026-10").length).toBeGreaterThanOrEqual(1);
    });

    expect(screen.getByText("42h")).toBeDefined();
    expect(screen.getByText("18")).toBeDefined();
    expect(screen.getByText("24")).toBeDefined();
    expect(screen.getByText(/Shipped Review Generator/)).toBeDefined();
  });

  it("switches to quarter and year wrapped views", async () => {
    render(<PeriodicReviewModal isOpen={true} onClose={() => {}} onToast={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Quarter")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Quarter"));
    await waitFor(() => {
      expect(api.periodicReview).toHaveBeenCalledWith("quarter", expect.stringContaining("-Q"));
    });

    fireEvent.click(screen.getByText("Year (Wrapped)"));
    await waitFor(() => {
      expect(api.periodicReview).toHaveBeenCalledWith("year", expect.stringMatching(/^\d{4}$/));
    });
  });

  it("copies review markdown to clipboard", async () => {
    const onToast = vi.fn();
    render(<PeriodicReviewModal isOpen={true} onClose={() => {}} onToast={onToast} />);

    await waitFor(() => {
      expect(screen.getByText("Copy")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Copy"));

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(mockReview.review_md);
      expect(onToast).toHaveBeenCalledWith("Review copied to clipboard");
    });
  });

  it("saves review as a note", async () => {
    const onToast = vi.fn();
    render(<PeriodicReviewModal isOpen={true} onClose={() => {}} onToast={onToast} />);

    await waitFor(() => {
      expect(screen.getByText("Save Note")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Save Note"));

    await waitFor(() => {
      expect(api.savePeriodicReviewAsNote).toHaveBeenCalledWith(
        "month",
        "2026-10",
        mockReview.review_md,
        mockReview.title,
      );
      expect(onToast).toHaveBeenCalledWith("Saved review as note");
    });
  });

  it("closes when close button is clicked", async () => {
    const onClose = vi.fn();
    render(<PeriodicReviewModal isOpen={true} onClose={onClose} onToast={() => {}} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Close review dialog")).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText("Close review dialog"));
    expect(onClose).toHaveBeenCalled();
  });
});
