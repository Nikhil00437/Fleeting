import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TasksView, {
  cyclePriority,
  formatDueDate,
  toLocalDateString,
  sortTasksStream,
  groupTasksByPriority,
  groupTasksByNote,
  toggleTaskAction,
  updateTaskPriorityAction,
  updateTaskDueDateAction,
  updateTaskTextAction,
  createQuickTaskAction,
} from "../TasksView";
import type { TaskItem, RepoInfo } from "../../types";
import { api } from "../../api";

// Mock api methods
vi.mock("../../api", () => ({
  api: {
    tasks: vi.fn(),
    toggleTask: vi.fn(),
    updateTask: vi.fn(),
    createTask: vi.fn(),
    deleteTask: vi.fn(),
    taskRepos: vi.fn(),
    note: vi.fn(),
    updateNote: vi.fn(),
    captureText: vi.fn(),
  },
}));

const mockTasks: TaskItem[] = [
  {
    id: "task-1",
    note_id: "note-1",
    note_title: "Sprint Planning",
    text: "Fix login authentication redirect bug",
    done: false,
    priority: "P1",
    due_date: "2026-10-01",
    repo: "fleeting",
    created_at: "2026-10-01T10:00:00Z",
    completed_at: null,
  },
  {
    id: "task-2",
    note_id: "note-1",
    note_title: "Sprint Planning",
    text: "Review PR #42",
    done: false,
    priority: "P2",
    due_date: "2026-10-02",
    repo: "fleeting",
    created_at: "2026-10-01T11:00:00Z",
    completed_at: null,
  },
  {
    id: "task-3",
    note_id: "note-2",
    note_title: "Design System Specs",
    text: "Refactor icon color palette tokens",
    done: false,
    priority: "P3",
    due_date: "2026-10-15",
    repo: "studio-ui",
    created_at: "2026-09-30T15:00:00Z",
    completed_at: null,
  },
  {
    id: "task-4",
    note_id: "note-3",
    note_title: "Legacy Tasks",
    text: "Completed archival migration",
    done: true,
    priority: "P2",
    due_date: null,
    repo: null,
    created_at: "2026-09-28T09:00:00Z",
    completed_at: "2026-09-29T12:00:00Z",
  },
];

const mockRepos: RepoInfo[] = [
  { name: "fleeting", path: "/home/nikhil/fleeting", task_count: 2 },
  { name: "studio-ui", path: "/home/nikhil/studio-ui", task_count: 1 },
];

describe("TasksView Component & Helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.tasks).mockResolvedValue(mockTasks);
    vi.mocked(api.taskRepos).mockResolvedValue(mockRepos);
  });

  describe("Helper Functions", () => {
    it("cycles priority P1 -> P2 -> P3 -> P1", () => {
      expect(cyclePriority("P1")).toBe("P2");
      expect(cyclePriority("P2")).toBe("P3");
      expect(cyclePriority("P3")).toBe("P1");
    });

    it("formats dates in local calendar time using toLocalDateString", () => {
      const d = new Date(2026, 9, 15); // Month is 0-indexed: 9 = October
      expect(toLocalDateString(d)).toBe("2026-10-15");
    });

    it("formats due dates with relative indicators and css badge classes", () => {
      // Overdue
      const overdue = formatDueDate("2020-01-01");
      expect(overdue.className).toContain("due-overdue");
      expect(overdue.label.toLowerCase()).toContain("overdue");

      // Overdue but completed task: badge must be muted and NOT alert red
      const overdueDone = formatDueDate("2020-01-01", undefined, true);
      expect(overdueDone.className).not.toContain("due-overdue");
      expect(overdueDone.className).toContain("text-ink-400");

      // No date
      const noDate = formatDueDate(null);
      expect(noDate.label).toBe("No date");
      expect(noDate.className).toBe("");
    });

    it("sorts stream tasks by done, priority (P1 < P2 < P3), then due date", () => {
      const sorted = sortTasksStream(mockTasks);
      expect(sorted[0].priority).toBe("P1");
      expect(sorted[1].priority).toBe("P2");
      expect(sorted[2].priority).toBe("P3");
      expect(sorted[3].done).toBe(true);
    });

    it("groups tasks by priority correctly", () => {
      const grouped = groupTasksByPriority(mockTasks);
      expect(grouped.P1.length).toBe(1);
      expect(grouped.P2.length).toBe(2);
      expect(grouped.P3.length).toBe(1);
      expect(grouped.P1[0].id).toBe("task-1");
    });

    it("groups tasks by note correctly", () => {
      const grouped = groupTasksByNote(mockTasks);
      expect(grouped.length).toBe(3);
      expect(grouped[0].noteId).toBe("note-1");
      expect(grouped[0].items.length).toBe(2);
    });
  });

  describe("TasksView Render", () => {
    it("renders loading shimmer when tasks are null", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
        />
      );
      expect(html).toContain("shimmer");
    });

    it("renders task items with priority badges, due dates, and repo pills", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
        />
      );

      // Priority badges
      expect(html).toContain("badge-p1");
      expect(html).toContain("P1");
      expect(html).toContain("badge-p2");
      expect(html).toContain("P2");
      expect(html).toContain("badge-p3");
      expect(html).toContain("P3");

      // Repo badges
      expect(html).toContain("fleeting");
      expect(html).toContain("studio-ui");

      // Task text
      expect(html).toContain("Fix login authentication redirect bug");
      expect(html).toContain("Review PR #42");
    });

    it("renders status tabs with counts", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
        />
      );

      expect(html).toContain("Open");
      expect(html).toContain("Completed");
      expect(html).toContain("All");
      // 3 open tasks, 1 completed, 4 total
      expect(html).toContain("3");
      expect(html).toContain("1");
      expect(html).toContain("4");
    });

    it("renders multi-facet filter chips (priority, due date, repo dropdown)", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
        />
      );

      // Priority chips in toolbar
      expect(html).toContain("P1");
      expect(html).toContain("P2");
      expect(html).toContain("P3");

      // Due date chips in toolbar
      expect(html).toContain("All Dates");
      expect(html).toContain("Overdue");
      expect(html).toContain("Today");
      expect(html).toContain("This Week");

      // Repo selector in toolbar
      expect(html).toContain("All Repos");
    });

    it("renders By Priority grouping mode with separate priority sections", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
          initialGroupMode="priority"
        />
      );

      expect(html).toContain("P1 — Urgent");
      expect(html).toContain("P2 — Normal");
      expect(html).toContain("P3 — Low");
    });

    it("renders By Note grouping mode with note cards", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
          initialGroupMode="note"
        />
      );

      expect(html).toContain("Sprint Planning");
      expect(html).toContain("Design System Specs");
    });

    it("renders quick task creator with priority and repo options", () => {
      const html = renderToStaticMarkup(
        <TasksView
          refreshKey={0}
          onOpenNote={vi.fn()}
          onToast={vi.fn()}
          onTasksChanged={vi.fn()}
          initialTasks={mockTasks}
          initialRepos={mockRepos}
        />
      );

      expect(html).toContain("New Action Item");
      expect(html).toContain("Add Task");
    });
  });

  describe("Action Handlers & Optimistic State", () => {
    it("toggleTaskAction optimistically toggles and calls api.toggleTask", async () => {
      const task = mockTasks[0];
      const toggled = { ...task, done: true };
      vi.mocked(api.toggleTask).mockResolvedValue(toggled);

      let currentList = [...mockTasks];
      const setList = (fn: (prev: TaskItem[]) => TaskItem[]) => {
        currentList = fn(currentList);
      };

      const onTasksChanged = vi.fn();
      const onToast = vi.fn();

      await toggleTaskAction(task, setList, onTasksChanged, onToast);

      expect(api.toggleTask).toHaveBeenCalledWith(task.id);
      expect(onTasksChanged).toHaveBeenCalled();
      expect(currentList.find((t) => t.id === task.id)?.done).toBe(true);
    });

    it("updateTaskPriorityAction updates priority and calls api.updateTask", async () => {
      const task = mockTasks[1]; // priority P2
      const updated = { ...task, priority: "P3" as const };
      vi.mocked(api.updateTask).mockResolvedValue(updated);

      let currentList = [...mockTasks];
      const setList = (fn: (prev: TaskItem[]) => TaskItem[]) => {
        currentList = fn(currentList);
      };

      const onTasksChanged = vi.fn();
      const onToast = vi.fn();

      await updateTaskPriorityAction(task, "P3", setList, onTasksChanged, onToast);

      expect(api.updateTask).toHaveBeenCalledWith(task.id, { priority: "P3" });
      expect(onTasksChanged).toHaveBeenCalled();
      expect(currentList.find((t) => t.id === task.id)?.priority).toBe("P3");
    });

    it("updateTaskDueDateAction updates due date and calls api.updateTask", async () => {
      const task = mockTasks[0];
      const updated = { ...task, due_date: "2026-10-10" };
      vi.mocked(api.updateTask).mockResolvedValue(updated);

      let currentList = [...mockTasks];
      const setList = (fn: (prev: TaskItem[]) => TaskItem[]) => {
        currentList = fn(currentList);
      };

      const onTasksChanged = vi.fn();
      const onToast = vi.fn();

      await updateTaskDueDateAction(task, "2026-10-10", setList, onTasksChanged, onToast);

      expect(api.updateTask).toHaveBeenCalledWith(task.id, { due_date: "2026-10-10" });
      expect(onTasksChanged).toHaveBeenCalled();
      expect(currentList.find((t) => t.id === task.id)?.due_date).toBe("2026-10-10");
    });

    it("updateTaskTextAction updates task title/text and calls api.updateTask", async () => {
      const task = mockTasks[0];
      const updated = { ...task, text: "New title for task" };
      vi.mocked(api.updateTask).mockResolvedValue(updated);

      let currentList = [...mockTasks];
      const setList = (fn: (prev: TaskItem[]) => TaskItem[]) => {
        currentList = fn(currentList);
      };

      const onTasksChanged = vi.fn();
      const onToast = vi.fn();

      await updateTaskTextAction(task, "New title for task", setList, onTasksChanged, onToast);

      expect(api.updateTask).toHaveBeenCalledWith(task.id, { text: "New title for task" });
      expect(onTasksChanged).toHaveBeenCalled();
      expect(currentList.find((t) => t.id === task.id)?.text).toBe("New title for task");
    });

    it("createQuickTaskAction calls api.createTask and adds new item", async () => {
      const created: TaskItem = {
        id: "task-new",
        note_id: "inbox",
        note_title: "Task Inbox",
        text: "Brand new created task",
        done: false,
        priority: "P1",
        due_date: "2026-10-05",
        repo: "fleeting",
        created_at: "2026-10-01T12:00:00Z",
        completed_at: null,
      };
      vi.mocked(api.createTask).mockResolvedValue(created);

      let currentList = [...mockTasks];
      const setList = (fn: (prev: TaskItem[]) => TaskItem[]) => {
        currentList = fn(currentList);
      };

      const onTasksChanged = vi.fn();
      const onToast = vi.fn();

      await createQuickTaskAction(
        {
          text: "Brand new created task",
          priority: "P1",
          due_date: "2026-10-05",
          repo: "fleeting",
        },
        setList,
        onTasksChanged,
        onToast
      );

      expect(api.createTask).toHaveBeenCalledWith({
        text: "Brand new created task",
        priority: "P1",
        due_date: "2026-10-05",
        repo: "fleeting",
      });
      expect(onTasksChanged).toHaveBeenCalled();
      expect(currentList[0].id).toBe("task-new");
    });
  });
});
