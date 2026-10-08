/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import ReportComparison from "../ReportComparison";
import { api } from "../../api";
import type { DailyLog } from "../../types";

vi.mock("../../api", () => ({
  api: {
    dailyLog: vi.fn(),
  },
}));

describe("ReportComparison (#71)", () => {
  const logA: DailyLog = {
    day: "2026-10-08",
    summary_md: "# Digest A\n\nDid task alpha and focus work.",
    model: "ollama",
    created_at: "2026-10-08T12:00:00Z",
  };

  const logB: DailyLog = {
    day: "2026-10-07",
    summary_md: "# Digest B\n\nDid task beta and focus work.",
    model: "ollama",
    created_at: "2026-10-07T12:00:00Z",
  };

  beforeEach(() => {
    vi.mocked(api.dailyLog).mockImplementation(async (d) => {
      if (d === "2026-10-08") return logA;
      if (d === "2026-10-07") return logB;
      return { day: d || "2026-10-08", summary_md: "No data", model: "fallback", created_at: null };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders both reports side-by-side", async () => {
    render(
      <ReportComparison
        dayA="2026-10-08"
        dayB="2026-10-07"
        onDayAChange={() => {}}
        onDayBChange={() => {}}
        onClose={() => {}}
        onToast={() => {}}
        refreshKey={0}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Side-by-Side Comparison")).toBeDefined();
    });

    expect(screen.getByText("2026-10-08")).toBeDefined();
    expect(screen.getByText("2026-10-07")).toBeDefined();
    expect(screen.getByText(/Did task alpha/)).toBeDefined();
    expect(screen.getByText(/Did task beta/)).toBeDefined();
  });

  it("toggles word diff highlighting", async () => {
    render(
      <ReportComparison
        dayA="2026-10-08"
        dayB="2026-10-07"
        onDayAChange={() => {}}
        onDayBChange={() => {}}
        onClose={() => {}}
        onToast={() => {}}
        refreshKey={0}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Show Word Diff")).toBeDefined();
    });

    fireEvent.click(screen.getByText("Show Word Diff"));

    await waitFor(() => {
      expect(screen.getByText("Hide Word Diff")).toBeDefined();
      expect(screen.getByText(/words/)).toBeDefined();
    });
  });

  it("calls navigation callbacks when stepping days", async () => {
    const onDayAChange = vi.fn();
    const onDayBChange = vi.fn();

    render(
      <ReportComparison
        dayA="2026-10-08"
        dayB="2026-10-07"
        onDayAChange={onDayAChange}
        onDayBChange={onDayBChange}
        onClose={() => {}}
        onToast={() => {}}
        refreshKey={0}
      />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Previous day A")).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText("Previous day A"));
    expect(onDayAChange).toHaveBeenCalledWith("2026-10-07");

    fireEvent.click(screen.getByLabelText("Next day B"));
    expect(onDayBChange).toHaveBeenCalledWith("2026-10-08");
  });

  it("calls onClose when exit comparison clicked", async () => {
    const onClose = vi.fn();

    render(
      <ReportComparison
        dayA="2026-10-08"
        dayB="2026-10-07"
        onDayAChange={() => {}}
        onDayBChange={() => {}}
        onClose={onClose}
        onToast={() => {}}
        refreshKey={0}
      />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Exit side-by-side comparison")).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText("Exit side-by-side comparison"));
    expect(onClose).toHaveBeenCalled();
  });
});
