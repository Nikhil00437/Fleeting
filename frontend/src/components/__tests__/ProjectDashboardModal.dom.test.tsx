/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ProjectDashboardModal } from "../ProjectDashboardModal";
import type { ProjectDashboard, ProjectSummary } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockSummaries: ProjectSummary[] = [
  { project: "fleeting", total_seconds: 7200, active_days: 3, last_active: "2026-10-08" },
  { project: "dotfiles", total_seconds: 1800, active_days: 1, last_active: "2026-10-07" },
];

const mockDashboard: ProjectDashboard = {
  project: "fleeting",
  total_seconds: 7200,
  window_seconds: 5400,
  active_days: 3,
  last_active: "2026-10-08",
  daily_breakdown: [
    { day: "2026-10-07", seconds: 1800 },
    { day: "2026-10-08", seconds: 3600 },
  ],
  apps: [
    { app: "ghostty", seconds: 5400, percent: 75.0 },
    { app: "firefox", seconds: 1800, percent: 25.0 },
  ],
  branches: [
    { branch: "main", seconds: 5400 },
    { branch: "feature/dash", seconds: 1800 },
  ],
  recent_sessions: [
    {
      id: 1,
      title: "fleeting: main.py",
      app_class: "ghostty",
      seconds: 3600,
      day: "2026-10-08",
      first_seen: "2026-10-08T10:00:00",
    },
  ],
  commits: [
    {
      repo: "fleeting",
      subject: "feat: project dashboard",
      author: "Nikhil",
      committed_at: "2026-10-08T12:00:00Z",
    },
  ],
  tasks: {
    total: 2,
    completed: 1,
    pending: 1,
    items: [
      {
        id: "t1",
        text: "Finish #167 dashboard",
        done: 0,
        priority: "P1",
        due_date: "2026-10-09",
        estimate_min: 60,
        spent_min: 30,
        repo: "fleeting",
        created_at: "2026-10-08T09:00:00Z",
        completed_at: null,
      },
      {
        id: "t2",
        text: "Fix auth",
        done: 1,
        priority: "P2",
        due_date: null,
        estimate_min: null,
        spent_min: null,
        repo: "fleeting",
        created_at: "2026-10-07T09:00:00Z",
        completed_at: "2026-10-08T10:00:00Z",
      },
    ],
  },
  notes: [
    {
      id: "n1",
      title: "Project Notes",
      created_at: "2026-10-08T08:00:00Z",
      tags: ["fleeting"],
    },
  ],
};

describe("ProjectDashboardModal (#167)", () => {
  it("renders project dashboard with KPIs, apps, branches, commits, tasks and notes", async () => {
    vi.spyOn(api, "projectsSummary").mockResolvedValue({ projects: mockSummaries });
    vi.spyOn(api, "projectDashboard").mockResolvedValue(mockDashboard);

    render(<ProjectDashboardModal initialProject="fleeting" onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Project Dashboard")).toBeDefined();
      expect(screen.getByText("Total Time")).toBeDefined();
      expect(screen.getByText("2h 0m")).toBeDefined(); // 7200s
      expect(screen.getByText("1h 30m")).toBeDefined(); // 5400s
      expect(screen.getByText("ghostty")).toBeDefined();
      expect(screen.getByText("main")).toBeDefined();
      expect(screen.getByText("feat: project dashboard")).toBeDefined();
      expect(screen.getByText("Finish #167 dashboard")).toBeDefined();
      expect(screen.getByText("Project Notes")).toBeDefined();
    });
  });

  it("calls onClose when close button clicked", async () => {
    vi.spyOn(api, "projectsSummary").mockResolvedValue({ projects: mockSummaries });
    vi.spyOn(api, "projectDashboard").mockResolvedValue(mockDashboard);

    const onClose = vi.fn();
    render(<ProjectDashboardModal initialProject="fleeting" onClose={onClose} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Close project dashboard")).toBeDefined();
    });

    fireEvent.click(screen.getByLabelText("Close project dashboard"));
    expect(onClose).toHaveBeenCalled();
  });

  it("switches project when select option changed", async () => {
    vi.spyOn(api, "projectsSummary").mockResolvedValue({ projects: mockSummaries });
    const dashSpy = vi.spyOn(api, "projectDashboard").mockResolvedValue(mockDashboard);

    render(<ProjectDashboardModal initialProject="fleeting" onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByLabelText("Select project")).toBeDefined();
    });

    fireEvent.change(screen.getByLabelText("Select project"), { target: { value: "dotfiles" } });

    await waitFor(() => {
      expect(dashSpy).toHaveBeenCalledWith("dotfiles", 30);
    });
  });
});
