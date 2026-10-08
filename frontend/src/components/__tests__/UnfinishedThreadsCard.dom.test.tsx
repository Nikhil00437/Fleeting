/**
 * @vitest-environment jsdom
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import UnfinishedThreadsCard from "../UnfinishedThreadsCard";
import { api } from "../../api";
import type { UnfinishedThread } from "../../types";

vi.mock("../../api", () => ({
  api: {
    unfinishedThreads: vi.fn(),
    resolveThread: vi.fn(),
    convertThreadToTask: vi.fn(),
  },
}));

describe("UnfinishedThreadsCard (#169)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders empty state when there are no unresolved threads", async () => {
    vi.mocked(api.unfinishedThreads).mockResolvedValueOnce([]);

    render(<UnfinishedThreadsCard />);

    await waitFor(() => {
      expect(screen.getByText(/All caught up! No unresolved threads/i)).toBeDefined();
    });
    expect(screen.getByText("0 threads")).toBeDefined();
  });

  it("renders list of unfinished threads with age and metadata badges", async () => {
    const mockThreads: UnfinishedThread[] = [
      {
        id: "t1",
        text: "Resolve database deadlocks in test suite",
        source_day: "2026-10-06",
        source_type: "daily_log",
        created_at: "2026-10-06T00:00:00Z",
        age_days: 3,
      },
      {
        id: "t2",
        text: "Fix OAuth callback redirect",
        source_day: "2026-10-04",
        source_type: "task",
        created_at: "2026-10-04T00:00:00Z",
        age_days: 5,
        waiting_for: "security approval",
      },
    ];

    vi.mocked(api.unfinishedThreads).mockResolvedValueOnce(mockThreads);

    render(<UnfinishedThreadsCard />);

    await waitFor(() => {
      expect(screen.getByText("Resolve database deadlocks in test suite")).toBeDefined();
      expect(screen.getByText("Fix OAuth callback redirect")).toBeDefined();
    });

    expect(screen.getByText("3d open")).toBeDefined();
    expect(screen.getByText("5d open")).toBeDefined();
    expect(screen.getByText("waiting: security approval")).toBeDefined();
    expect(screen.getByText("2 threads")).toBeDefined();
  });

  it("resolves a thread and removes it from list", async () => {
    const onToast = vi.fn();
    const mockThreads: UnfinishedThread[] = [
      {
        id: "t1",
        text: "Need QA signoff",
        source_day: "2026-10-07",
        source_type: "daily_log",
        created_at: "2026-10-07T00:00:00Z",
        age_days: 2,
      },
    ];

    vi.mocked(api.unfinishedThreads).mockResolvedValueOnce(mockThreads);
    vi.mocked(api.resolveThread).mockResolvedValueOnce({ ok: true, thread_id: "t1", action: "resolve" });

    render(<UnfinishedThreadsCard onToast={onToast} />);

    await waitFor(() => {
      expect(screen.getByText("Need QA signoff")).toBeDefined();
    });

    const resolveBtn = screen.getByRole("button", { name: /Mark "Need QA signoff" as resolved/i });
    fireEvent.click(resolveBtn);

    await waitFor(() => {
      expect(api.resolveThread).toHaveBeenCalledWith("t1", "resolve");
      expect(screen.queryByText("Need QA signoff")).toBeNull();
    });
    expect(onToast).toHaveBeenCalledWith("Thread marked resolved");
  });

  it("converts a thread to a task", async () => {
    const onToast = vi.fn();
    const mockThreads: UnfinishedThread[] = [
      {
        id: "t2",
        text: "Write integration tests for payment gateway",
        source_day: "2026-10-05",
        source_type: "daily_log",
        created_at: "2026-10-05T00:00:00Z",
        age_days: 4,
      },
    ];

    vi.mocked(api.unfinishedThreads).mockResolvedValueOnce(mockThreads);
    vi.mocked(api.convertThreadToTask).mockResolvedValueOnce({
      ok: true,
      task: {
        id: "task-100",
        note_id: "inbox-note",
        repo: null,
        text: "Write integration tests for payment gateway",
        done: false,
        priority: "P2",
        list: "inbox",
        created_at: "2026-10-09T00:00:00Z",
        completed_at: null,
        due_date: null,
      },
    });

    render(<UnfinishedThreadsCard onToast={onToast} />);

    await waitFor(() => {
      expect(screen.getByText("Write integration tests for payment gateway")).toBeDefined();
    });

    const taskBtn = screen.getByRole("button", { name: /Convert "Write integration tests for payment gateway" to task/i });
    fireEvent.click(taskBtn);

    await waitFor(() => {
      expect(api.convertThreadToTask).toHaveBeenCalledWith("t2", "Write integration tests for payment gateway");
      expect(screen.queryByText("Write integration tests for payment gateway")).toBeNull();
    });
    expect(onToast).toHaveBeenCalledWith("Converted thread to task");
  });
});
