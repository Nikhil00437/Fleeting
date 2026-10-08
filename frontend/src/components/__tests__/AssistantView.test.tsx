import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import AssistantView, {
  parseCitations,
  renderFormattedContent,
  sendAssistantPromptAction,
  type AssistantDisplayMessage,
} from "../AssistantView";
import type {
  AssistantChatOut,
  AssistantSuggestionsOut,
  ChatMessage,
  RepoInfo,
} from "../../types";
import { api } from "../../api";

// Mock API module
vi.mock("../../api", () => ({
  api: {
    assistantChat: vi.fn(),
    assistantSuggestions: vi.fn(),
    taskRepos: vi.fn(),
  },
}));

const mockSuggestions: AssistantSuggestionsOut = {
  suggestions: [
    "What urgent P1 tasks do I have?",
    "Summarize recent captures from this week",
    "Find notes about database migrations",
  ],
};

const mockRepos: RepoInfo[] = [
  { name: "fleeting", path: "/home/nikhil/fleeting", task_count: 5 },
  { name: "studio", path: "/home/nikhil/studio", task_count: 2 },
];

const mockAssistantResponse: AssistantChatOut = {
  message: {
    role: "assistant",
    content:
      "You have 1 urgent task: [[task:t-101|Fix production OAuth token expiration]] from [[note:n-202|Sprint Planning Oct 2]].",
  },
  sources: [
    {
      id: "n-202",
      title: "Sprint Planning Oct 2",
      type: "text",
      kind: "note",
      snippet: "Discussion of urgent P1 tickets including production OAuth fix.",
    },
    {
      id: "t-101",
      title: "Fix production OAuth token expiration",
      type: "task",
      kind: "task",
      snippet: "Priority: P1 · Due: 2026-10-03",
    },
  ],
  context_used: {
    notes_count: 2,
    tasks_count: 3,
    logs_count: 1,
  },
};

describe("AssistantView Component & Logic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.assistantSuggestions).mockResolvedValue(mockSuggestions);
    vi.mocked(api.taskRepos).mockResolvedValue(mockRepos);
    vi.mocked(api.assistantChat).mockResolvedValue(mockAssistantResponse);
  });

  describe("parseCitations helper", () => {
    it("handles empty string", () => {
      expect(parseCitations("")).toEqual([]);
    });

    it("returns plain text token when no citations present", () => {
      const tokens = parseCitations("Hello world, this is a plain message.");
      expect(tokens).toEqual([
        {
          type: "text",
          content: "Hello world, this is a plain message.",
        },
      ]);
    });

    it("parses note citation [[note:id|title]]", () => {
      const tokens = parseCitations("Refer to [[note:abc-123|Architecture Guide]] for details.");
      expect(tokens).toEqual([
        { type: "text", content: "Refer to " },
        {
          type: "note-citation",
          id: "abc-123",
          title: "Architecture Guide",
          content: "[[note:abc-123|Architecture Guide]]",
        },
        { type: "text", content: " for details." },
      ]);
    });

    it("parses task citation [[task:id|text]]", () => {
      const tokens = parseCitations("Action needed: [[task:tsk-99|Deploy staging v2]].");
      expect(tokens).toEqual([
        { type: "text", content: "Action needed: " },
        {
          type: "task-citation",
          id: "tsk-99",
          title: "Deploy staging v2",
          content: "[[task:tsk-99|Deploy staging v2]]",
        },
        { type: "text", content: "." },
      ]);
    });

    it("parses multiple mixed citations in sequence", () => {
      const raw =
        "Linked [[note:n1|Note One]] and task [[task:t2|Task Two]] and [[note:n3|Note Three]].";
      const tokens = parseCitations(raw);
      expect(tokens.length).toBe(7);
      expect(tokens[1].type).toBe("note-citation");
      expect(tokens[1].id).toBe("n1");
      expect(tokens[3].type).toBe("task-citation");
      expect(tokens[3].id).toBe("t2");
      expect(tokens[5].type).toBe("note-citation");
      expect(tokens[5].id).toBe("n3");
    });
  });

  describe("renderFormattedContent helper", () => {
    it("renders clickable note citation with title", () => {
      const onOpenNote = vi.fn();
      const node = renderFormattedContent(
        "Check [[note:n-42|Release Notes v1.0]] please.",
        onOpenNote
      );
      const html = renderToStaticMarkup(node as React.ReactElement);

      expect(html).toContain("data-testid=\"citation-note-n-42\"");
      expect(html).toContain("Release Notes v1.0");
      expect(html).toContain("📄");
    });

    it("renders clickable task citation with title", () => {
      const onOpenTasks = vi.fn();
      const node = renderFormattedContent(
        "See [[task:t-77|Refactor API client]] now.",
        vi.fn(),
        onOpenTasks
      );
      const html = renderToStaticMarkup(node as React.ReactElement);

      expect(html).toContain("data-testid=\"citation-task-t-77\"");
      expect(html).toContain("Refactor API client");
      expect(html).toContain("☑");
    });

    it("formats markdown bold tokens and bullet lists", () => {
      const raw = "Here is the plan:\n- **Item 1**: Done\n- **Item 2**: Pending";
      const node = renderFormattedContent(raw, vi.fn());
      const html = renderToStaticMarkup(node as React.ReactElement);

      expect(html).toContain("<strong");
      expect(html).toContain("Item 1");
      expect(html).toContain("Item 2");
      expect(html).toContain("•");
    });
  });

  describe("sendAssistantPromptAction logic", () => {
    it("calls api.assistantChat with messages payload and updates state", async () => {
      let messages: AssistantDisplayMessage[] = [];
      const setMessages = (
        action: React.SetStateAction<AssistantDisplayMessage[]>
      ) => {
        if (typeof action === "function") {
          messages = action(messages);
        } else {
          messages = action;
        }
      };

      let loading = false;
      const setLoading = (
        action: React.SetStateAction<boolean>
      ) => {
        if (typeof action === "function") {
          loading = action(loading);
        } else {
          loading = action;
        }
      };

      const onToast = vi.fn();

      await sendAssistantPromptAction(
        "What P1 tasks do I have?",
        [],
        setMessages,
        setLoading,
        onToast,
        { repo: "fleeting" }
      );

      expect(api.assistantChat).toHaveBeenCalledWith({
        messages: [{ role: "user", content: "What P1 tasks do I have?" }],
        repo: "fleeting",
        type: undefined,
      });

      expect(messages.length).toBe(2);
      expect(messages[0].role).toBe("user");
      expect(messages[0].content).toBe("What P1 tasks do I have?");

      expect(messages[1].role).toBe("assistant");
      expect(messages[1].content).toContain("Fix production OAuth token expiration");
      expect(messages[1].sources?.length).toBe(2);
      expect(messages[1].context_used?.notes_count).toBe(2);
      expect(loading).toBe(false);
    });

    it("ignores whitespace-only prompts", async () => {
      const setMessages = vi.fn();
      const setLoading = vi.fn();
      const onToast = vi.fn();

      await sendAssistantPromptAction(
        "   \n  ",
        [],
        setMessages,
        setLoading,
        onToast
      );

      expect(api.assistantChat).not.toHaveBeenCalled();
      expect(setMessages).not.toHaveBeenCalled();
    });

    it("handles API failure by toasting error and rendering fallback assistant message", async () => {
      vi.mocked(api.assistantChat).mockRejectedValueOnce(new Error("Connection refused (Ollama offline)"));

      let messages: AssistantDisplayMessage[] = [];
      const setMessages = (
        action: React.SetStateAction<AssistantDisplayMessage[]>
      ) => {
        if (typeof action === "function") {
          messages = action(messages);
        } else {
          messages = action;
        }
      };
      const setLoading = vi.fn();
      const onToast = vi.fn();

      await sendAssistantPromptAction(
        "Hello assistant",
        [],
        setMessages,
        setLoading,
        onToast
      );

      expect(onToast).toHaveBeenCalledWith(
        expect.stringContaining("Connection refused"),
        "err"
      );
      expect(messages.length).toBe(2);
      expect(messages[1].role).toBe("assistant");
      expect(messages[1].isError).toBe(true);
      expect(messages[1].content).toContain("Error fetching assistant response");
    });

    it("filters out prior error messages from subsequent assistantChat payloads", async () => {
      vi.mocked(api.assistantChat).mockResolvedValueOnce({
        message: { role: "assistant", content: "Recovered answer" },
        sources: [],
        context_used: { notes_count: 0, tasks_count: 0, logs_count: 0 },
      });

      const priorMessages: AssistantDisplayMessage[] = [
        { id: "1", role: "user", content: "Query 1" },
        { id: "2", role: "assistant", content: "⚠️ Error fetching response", isError: true },
      ];

      let messages = [...priorMessages];
      const setMessages = (action: any) => {
        if (typeof action === "function") {
          messages = action(messages);
        } else {
          messages = action;
        }
      };

      await sendAssistantPromptAction(
        "Query 2",
        priorMessages,
        setMessages,
        vi.fn(),
        vi.fn()
      );

      expect(api.assistantChat).toHaveBeenCalledWith(
        expect.objectContaining({
          messages: [
            { role: "user", content: "Query 1" },
            { role: "user", content: "Query 2" },
          ],
        })
      );
    });
  });

  describe("AssistantView Component Rendering", () => {
    it("renders empty state with starter suggestion chips", () => {
      const html = renderToStaticMarkup(
        <AssistantView
          onOpenNote={vi.fn()}
          onOpenTasks={vi.fn()}
          onToast={vi.fn()}
          initialSuggestions={mockSuggestions.suggestions}
        />
      );

      expect(html).toContain("Ask Fleeting");
      expect(html).toContain("How can I help you today?");
      expect(html).toContain("Starter Suggestions");
      expect(html).toContain("What urgent P1 tasks do I have?");
      expect(html).toContain("Summarize recent captures from this week");
    });

    it("renders active conversation messages with user and assistant dialogue", () => {
      const initialMessages: ChatMessage[] = [
        { role: "user", content: "Tell me about my tasks." },
        {
          role: "assistant",
          content: "Here is your note: [[note:n-123|Sprint Roadmap]].",
        },
      ];

      const html = renderToStaticMarkup(
        <AssistantView
          onOpenNote={vi.fn()}
          onOpenTasks={vi.fn()}
          onToast={vi.fn()}
          initialMessages={initialMessages}
        />
      );

      expect(html).toContain("Tell me about my tasks.");
      expect(html).toContain("data-testid=\"citation-note-n-123\"");
      expect(html).toContain("Sprint Roadmap");
      expect(html).toContain("data-testid=\"clear-chat-btn\"");
    });

    it("renders the New conversation button when messages exist", () => {
      const html = renderToStaticMarkup(
        <AssistantView
          onOpenNote={vi.fn()}
          onOpenTasks={vi.fn()}
          onToast={vi.fn()}
          initialMessages={[{ role: "user", content: "Ping" }]}
        />
      );

      expect(html).toContain("data-testid=\"clear-chat-btn\"");
      // #111: clearing became starting a new thread — the old one is saved.
      expect(html).toContain("New");
    });

    it("does not render the New conversation button when dialogue is empty", () => {
      const html = renderToStaticMarkup(
        <AssistantView
          onOpenNote={vi.fn()}
          onOpenTasks={vi.fn()}
          onToast={vi.fn()}
          initialMessages={[]}
        />
      );

      expect(html).not.toContain("data-testid=\"clear-chat-btn\"");
    });

    it("renders input field with send prompt button", () => {
      const html = renderToStaticMarkup(
        <AssistantView
          onOpenNote={vi.fn()}
          onOpenTasks={vi.fn()}
          onToast={vi.fn()}
        />
      );

      expect(html).toContain("data-testid=\"assistant-input\"");
      expect(html).toContain("data-testid=\"send-prompt-btn\"");
      expect(html).toContain("Ask anything about your notes, tasks, or recent activity…");
    });
  });
});

// ============================================================================
// Destructive action confirmation
// ============================================================================

describe("destructive action confirmation", () => {
  beforeEach(() => {
    vi.mocked(api.assistantChat).mockReset();
  });

  it("keeps a pending_action returned by the assistant", async () => {
    vi.mocked(api.assistantChat).mockResolvedValue({
      message: {
        role: "assistant",
        content: "Delete every task — waiting for your confirmation.",
      },
      sources: [],
      context_used: { notes_count: 0, tasks_count: 0, logs_count: 0 },
      pending_action: {
        tool: "delete_tasks",
        params: { all: true },
        summary: "Delete every task",
      },
    });

    const setMessages = vi.fn();
    await sendAssistantPromptAction(
      "delete all tasks",
      [],
      setMessages,
      vi.fn(),
      vi.fn(),
    );

    // setMessages is called with the new list, then with an updater fn.
    const calls = setMessages.mock.calls;
    const updater = calls[calls.length - 1][0];
    const base = calls[calls.length - 2][0] as AssistantDisplayMessage[];
    const added = (typeof updater === "function" ? updater(base) : updater) as AssistantDisplayMessage[];

    expect(added[added.length - 1].pending_action?.tool).toBe("delete_tasks");
    expect(added[added.length - 1].pending_action?.summary).toBe("Delete every task");
  });

  it("sends confirm:true when the option is set", async () => {
    vi.mocked(api.assistantChat).mockResolvedValue({
      message: { role: "assistant", content: "Deleted 3 active tasks." },
      sources: [],
      context_used: { notes_count: 0, tasks_count: 0, logs_count: 0 },
      pending_action: null,
    });

    await sendAssistantPromptAction(
      "delete all tasks",
      [],
      vi.fn(),
      vi.fn(),
      vi.fn(),
      { confirm: true },
    );

    expect(api.assistantChat).toHaveBeenCalledWith(
      expect.objectContaining({ confirm: true }),
    );
  });

  it("omits confirm when not confirming", async () => {
    vi.mocked(api.assistantChat).mockResolvedValue({
      message: { role: "assistant", content: "ok" },
      sources: [],
      context_used: { notes_count: 0, tasks_count: 0, logs_count: 0 },
    });

    await sendAssistantPromptAction("hi", [], vi.fn(), vi.fn(), vi.fn());

    expect(api.assistantChat).toHaveBeenCalledWith(
      expect.not.objectContaining({ confirm: true }),
    );
  });

  it("renders a confirm control for a pending action", () => {
    const msg: AssistantDisplayMessage = {
      id: "m1",
      role: "assistant",
      content: "Delete every task — waiting for your confirmation.",
      timestamp: new Date().toISOString(),
      pending_action: {
        tool: "delete_tasks",
        params: { all: true },
        summary: "Delete every task",
      },
    };

    const html = renderToStaticMarkup(
      <AssistantView
        onOpenNote={() => {}}
        onToast={() => {}}
        initialMessages={[msg]}
      />,
    );

    expect(html).toContain("Delete every task");
    expect(html).toContain('data-testid="confirm-action"');
    expect(html).toContain('data-testid="cancel-action"');
  });

  it("renders no confirm control without a pending action", () => {
    const msg: AssistantDisplayMessage = {
      id: "m2",
      role: "assistant",
      content: "Nothing to confirm here.",
      timestamp: new Date().toISOString(),
    };

    const html = renderToStaticMarkup(
      <AssistantView onOpenNote={() => {}} onToast={() => {}} initialMessages={[msg]} />,
    );

    expect(html).not.toContain("data-testid=\"confirm-action\"");
  });
});
