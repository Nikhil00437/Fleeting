/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import ReportPlaygroundModal from "../ReportPlaygroundModal";
import { api } from "../../api";
import type { ReportPlaygroundResult } from "../../types";

vi.mock("../../api", () => ({
  api: {
    reportPlayground: vi.fn(),
    editDailyLog: vi.fn(),
  },
}));

describe("ReportPlaygroundModal (#349)", () => {
  const mockResult: ReportPlaygroundResult = {
    day: "2026-10-07",
    system_prompt: "You are an insightful personal engineering assistant...\nAdditional user instructions: Focus strictly on code architecture.",
    transcript: "Window: 2026-10-07 00:00 → 2026-10-08 00:00\n- cursor: 2h 00m\n- git: feat: add playground",
    preview_md: "# Daily Digest — 2026-10-07\n\n## Executive Summary\nFocused heavily on code architecture.",
    model: "fallback",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.reportPlayground).mockResolvedValue(mockResult);
    vi.mocked(api.editDailyLog).mockResolvedValue({ ok: true, edited: 1, body: mockResult.preview_md });

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

  it("renders modal controls and presets when open", () => {
    render(
      <ReportPlaygroundModal
        isOpen={true}
        onClose={() => {}}
        onToast={() => {}}
        initialDay="2026-10-07"
      />
    );

    expect(screen.getByText("Report Playground")).toBeDefined();
    expect(screen.getByText("Code & Architecture")).toBeDefined();
    expect(screen.getByText("Crisp Bullets (≤4)")).toBeDefined();
    expect(screen.getByRole("button", { name: /Run Playground Test/i })).toBeDefined();
  });

  it("sets prompt from preset when preset clicked", () => {
    render(
      <ReportPlaygroundModal
        isOpen={true}
        onClose={() => {}}
        onToast={() => {}}
        initialDay="2026-10-07"
      />
    );

    const presetBtn = screen.getByText("Code & Architecture");
    fireEvent.click(presetBtn);

    const textarea = screen.getByPlaceholderText(/Highlight backend architectural improvements/i) as HTMLTextAreaElement;
    expect(textarea.value).toContain("Focus strictly on software engineering");
  });

  it("runs playground test and switches tabs to inspect prompt and transcript", async () => {
    const onToast = vi.fn();
    render(
      <ReportPlaygroundModal
        isOpen={true}
        onClose={() => {}}
        onToast={onToast}
        initialDay="2026-10-07"
      />
    );

    const runBtn = screen.getByRole("button", { name: /Run Playground Test/i });
    fireEvent.click(runBtn);

    await waitFor(() => {
      expect(api.reportPlayground).toHaveBeenCalled();
      expect(onToast).toHaveBeenCalledWith("Playground test completed");
    });

    // Preview rendered
    expect(screen.getByText(/Focused heavily on code architecture/i)).toBeDefined();

    // Switch to System Prompt tab
    const promptTab = screen.getByRole("button", { name: "System Prompt" });
    fireEvent.click(promptTab);
    expect(screen.getByText(/Exact system prompt dispatched/i)).toBeDefined();

    // Switch to Telemetry Transcript tab
    const transcriptTab = screen.getByRole("button", { name: "Telemetry Transcript" });
    fireEvent.click(transcriptTab);
    expect(screen.getByText(/Synthesized window activity, files/i)).toBeDefined();
  });

  it("copies preview and applies preview as official daily report", async () => {
    const onToast = vi.fn();
    const onClose = vi.fn();
    render(
      <ReportPlaygroundModal
        isOpen={true}
        onClose={onClose}
        onToast={onToast}
        initialDay="2026-10-07"
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Run Playground Test/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Copy/i })).toBeDefined();
    });

    // Copy to clipboard
    fireEvent.click(screen.getByRole("button", { name: /Copy/i }));
    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(mockResult.preview_md);
      expect(onToast).toHaveBeenCalledWith("Playground preview copied to clipboard");
    });

    // Apply as report
    const applyBtn = screen.getByRole("button", { name: /Apply as Report/i });
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(api.editDailyLog).toHaveBeenCalledWith("2026-10-07", mockResult.preview_md);
      expect(onToast).toHaveBeenCalledWith("Saved playground preview as daily report for 2026-10-07");
      expect(onClose).toHaveBeenCalled();
    });
  });
});
