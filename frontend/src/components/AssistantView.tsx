import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import {
  BotIcon,
  FolderIcon,
  SendIcon,
  SparkIcon,
  TrashIcon,
} from "./Icons";
import type {
  ChatMessage,
  PendingAction,
  RepoInfo,
  SourceRef,
} from "../types";

export interface Props {
  onOpenNote: (id: string) => void;
  onOpenTasks?: () => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
  initialMessages?: ChatMessage[];
  initialSuggestions?: string[];
}

export interface AssistantDisplayMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  isError?: boolean;
  sources?: SourceRef[];
  context_used?: {
    notes_count: number;
    tasks_count: number;
    logs_count: number;
  };
  pending_action?: PendingAction | null;
  timestamp?: string;
}

export interface ParsedCitationToken {
  type: "text" | "note-citation" | "task-citation";
  content: string;
  id?: string;
  title?: string;
}

export function parseCitations(text: string): ParsedCitationToken[] {
  const regex = /\[\[(note|task):([^|\]]+)\|([^\]]+)\]\]/g;
  const tokens: ParsedCitationToken[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({
        type: "text",
        content: text.slice(lastIndex, match.index),
      });
    }
    tokens.push({
      type: match[1] === "note" ? "note-citation" : "task-citation",
      id: match[2],
      title: match[3],
      content: match[0],
    });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    tokens.push({
      type: "text",
      content: text.slice(lastIndex),
    });
  }

  return tokens;
}

export function renderFormattedContent(
  text: string,
  onOpenNote: (id: string) => void,
  onOpenTasks?: () => void
): React.ReactNode {
  const tokens = parseCitations(text);

  return (
    <div className="leading-relaxed text-ink-100 text-[13.5px]">
      {tokens.map((token, idx) => {
        if (token.type === "note-citation" && token.id) {
          return (
            <button
              key={`token-${idx}`}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenNote(token.id!);
              }}
              data-testid={`citation-note-${token.id}`}
              className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded-md border border-amber-500/30 bg-amber-500/15 text-amber-200 text-xs font-medium hover:bg-amber-500/25 hover:border-amber-400 transition-colors cursor-pointer align-baseline"
              title={`Open note: ${token.title}`}
            >
              <span className="text-[11px]">📄</span>
              <span className="font-semibold underline decoration-amber-400/40 underline-offset-2">
                {token.title}
              </span>
            </button>
          );
        }

        if (token.type === "task-citation" && token.id) {
          return (
            <button
              key={`token-${idx}`}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenTasks?.();
              }}
              data-testid={`citation-task-${token.id}`}
              className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded-md border border-emerald-500/30 bg-emerald-500/15 text-emerald-200 text-xs font-medium hover:bg-emerald-500/25 hover:border-emerald-400 transition-colors cursor-pointer align-baseline"
              title={`Open tasks: ${token.title}`}
            >
              <span className="text-[11px]">☑</span>
              <span className="font-semibold underline decoration-emerald-400/40 underline-offset-2">
                {token.title}
              </span>
            </button>
          );
        }

        // Render plain text segments with simple markdown linebreaks / bullet formatting
        const lines = token.content.split("\n");
        return (
          <span key={`text-${idx}`}>
            {lines.map((line, lineIdx) => {
              const isBullet = line.trimStart().startsWith("- ") || line.trimStart().startsWith("* ");
              const cleanedLine = isBullet ? line.trimStart().slice(2) : line;

              // Simple bold formatting replacement (**bold**)
              const parts = cleanedLine.split(/(\*\*[^*]+\*\*)/g);

              const formattedParts = parts.map((part, pIdx) => {
                if (part.startsWith("**") && part.endsWith("**")) {
                  return (
                    <strong key={`b-${pIdx}`} className="font-semibold text-ink-100">
                      {part.slice(2, -2)}
                    </strong>
                  );
                }
                return part;
              });

              return (
                <span key={`l-${lineIdx}`}>
                  {lineIdx > 0 && <br />}
                  {isBullet && <span className="inline-block w-3 text-ember-400">•</span>}
                  {formattedParts}
                </span>
              );
            })}
          </span>
        );
      })}
    </div>
  );
}

export async function sendAssistantPromptAction(
  prompt: string,
  currentMessages: AssistantDisplayMessage[],
  setMessages: React.Dispatch<React.SetStateAction<AssistantDisplayMessage[]>>,
  setLoading: React.Dispatch<React.SetStateAction<boolean>>,
  onToast: (msg: string, kind?: "ok" | "err") => void,
  options?: { repo?: string | null; type?: string | null; confirm?: boolean }
) {
  const trimmed = prompt.trim();
  if (!trimmed) return;

  const userMsg: AssistantDisplayMessage = {
    id: `user-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
    role: "user",
    content: trimmed,
    timestamp: new Date().toISOString(),
  };

  const nextList = [...currentMessages, userMsg];
  setMessages(nextList);
  setLoading(true);

  try {
    const payloadMessages = nextList
      .filter((m) => !m.isError)
      .map((m) => ({
        role: m.role,
        content: m.content,
      }));

    const res = await api.assistantChat({
      messages: payloadMessages,
      repo: options?.repo && options.repo !== "all" ? options.repo : undefined,
      type: options?.type && options.type !== "all" ? options.type : undefined,
      ...(options?.confirm ? { confirm: true } : {}),
    });

    const assistantMsg: AssistantDisplayMessage = {
      id: `asst-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      role: res.message.role,
      content: res.message.content,
      sources: res.sources,
      context_used: res.context_used,
      pending_action: res.pending_action ?? null,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, assistantMsg]);
  } catch (err) {
    const errorText = err instanceof Error ? err.message : String(err);
    onToast(`Assistant query failed: ${errorText}`, "err");
    const errorMsg: AssistantDisplayMessage = {
      id: `err-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      role: "assistant",
      isError: true,
      content: `⚠️ Error fetching assistant response: ${errorText}. Please verify that your local LLM service is active or inspect settings.`,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, errorMsg]);
  } finally {
    setLoading(false);
  }
}

export default function AssistantView({
  onOpenNote,
  onOpenTasks,
  onToast,
  initialMessages,
  initialSuggestions,
}: Props) {
  const [messages, setMessages] = useState<AssistantDisplayMessage[]>(() =>
    initialMessages
      ? initialMessages.map((m, idx) => ({
          ...m,
          id: `init-${idx}`,
          timestamp: new Date().toISOString(),
        }))
      : []
  );

  const [suggestions, setSuggestions] = useState<string[]>(initialSuggestions ?? []);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [repos, setRepos] = useState<RepoInfo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<string>("all");
  const [expandedSources, setExpandedSources] = useState<Record<string, boolean>>({});

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Load starter suggestions if not provided
  useEffect(() => {
    if (!initialSuggestions || initialSuggestions.length === 0) {
      api
        .assistantSuggestions()
        .then((res) => {
          if (res.suggestions && res.suggestions.length > 0) {
            setSuggestions(res.suggestions);
          }
        })
        .catch(() => {});
    }
  }, [initialSuggestions]);

  // Load available task repos for optional filtering
  useEffect(() => {
    api
      .taskRepos()
      .then(setRepos)
      .catch(() => {});
  }, []);

  // Auto-scroll to bottom of message thread
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSendPrompt = (promptText: string) => {
    if (loading) return;
    setInput("");
    sendAssistantPromptAction(
      promptText,
      messages,
      setMessages,
      setLoading,
      onToast,
      { repo: selectedRepo }
    );
  };

  const handleConfirmAction = (msg: AssistantDisplayMessage) => {
    if (loading || !msg.pending_action) return;
    // Re-send the prompt that produced the pending action, this time approved.
    const priorUserMsg = [...messages]
      .reverse()
      .find((m) => m.role === "user" && !m.isError);
    const prompt = priorUserMsg?.content ?? msg.pending_action.summary;
    sendAssistantPromptAction(prompt, messages, setMessages, setLoading, onToast, {
      repo: selectedRepo,
      confirm: true,
    });
  };

  const handleCancelAction = (msgId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              pending_action: null,
              content: `${m.content}\n\n(cancelled)`,
            }
          : m
      )
    );
    onToast("Action cancelled");
  };

  const handleClearChat = () => {
    setMessages([]);
    onToast("Chat conversation cleared");
    inputRef.current?.focus();
  };

  const toggleSources = (msgId: string) => {
    setExpandedSources((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Workbench Header Toolbar */}
      <div className="app-toolbar flex h-12 shrink-0 items-center justify-between gap-3 px-5 border-b">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-7 w-7 items-center justify-center rounded-xl bg-gradient-to-br from-ember-500/20 to-ember-600/20 bg-ember-500/10 text-ember-300 ring-1 ring-ember-400/30 shadow-xs">
            <BotIcon className="h-4 w-4 text-ember-400" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xs font-bold tracking-tight text-ink-100 flex items-center gap-1.5">
              <span>Ask Fleeting</span>
              <span className="rounded-md border border-ember-500/30 bg-ember-500/10 px-1.5 py-0.2 font-mono text-[9px] font-medium text-ember-300">
                Assistant
              </span>
            </h1>
          </div>
        </div>

        {/* Toolbar Controls: Repo Filter & Clear Chat */}
        <div className="flex items-center gap-2">
          {repos.length > 0 && (
            <div className="flex items-center gap-1.5 rounded-xl border border-ink-800/90 bg-ink-950/85 px-2 py-1 text-xs">
              <span className="font-mono text-[10px] text-ink-400">Repo:</span>
              <select
                value={selectedRepo}
                onChange={(e) => setSelectedRepo(e.target.value)}
                className="bg-transparent text-xs text-ink-200 outline-none cursor-pointer"
              >
                <option value="all">All repositories</option>
                {repos.map((r) => (
                  <option key={r.name} value={r.name}>
                    {r.name} ({r.task_count})
                  </option>
                ))}
              </select>
            </div>
          )}

          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleClearChat}
              className="flex items-center gap-1.5 rounded-xl border border-ink-800/90 bg-ink-950/80 px-2.5 py-1 text-xs text-ink-300 transition-colors hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300"
              title="Clear conversation"
              data-testid="clear-chat-btn"
            >
              <TrashIcon className="h-3 w-3" />
              <span>Clear</span>
            </button>
          )}

          <span className="hidden md:inline rounded-lg border border-ink-800/80 bg-ink-950/60 px-2.5 py-1 font-mono text-[10.5px] text-ink-400">
            Grounded RAG · Multi-Turn
          </span>
        </div>
      </div>

      {/* Main Conversation Thread Viewport */}
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6 space-y-4"
        data-testid="message-thread"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full max-w-xl mx-auto py-12 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-ember-500/20 to-ember-600/20 bg-ember-500/10 ring-1 ring-ember-400/30 text-ember-300 shadow-lg">
              <BotIcon className="h-7 w-7 text-ember-400" />
            </div>
            <h2 className="mt-4 text-base font-bold tracking-tight text-ink-100">
              How can I help you today?
            </h2>
            <p className="mt-1.5 text-xs text-ink-400 max-w-md leading-relaxed">
              Ask grounded questions about your captured notes, open action items, or daily activity logs. Answers cite relevant knowledge cards directly.
            </p>

            {suggestions.length > 0 && (
              <div className="mt-8 w-full space-y-2.5">
                <p className="micro-label !text-[10px] text-ink-400">Starter Suggestions</p>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {suggestions.map((suggestion, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => handleSendPrompt(suggestion)}
                      className="group flex items-center gap-2 rounded-xl border border-ink-800/80 bg-ink-950/70 px-3.5 py-2 text-xs text-ink-200 transition-all hover:border-ember-400/40 hover:bg-ink-900 hover:text-ember-200 shadow-sm text-left cursor-pointer"
                      data-testid={`suggestion-chip-${idx}`}
                    >
                      <SparkIcon className="h-3 w-3 text-ember-400 group-hover:scale-110 transition-transform shrink-0" />
                      <span>{suggestion}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-5">
            {messages.map((msg) => {
              const isUser = msg.role === "user";
              const isExpanded = expandedSources[msg.id] ?? true;

              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
                  data-testid={`message-${msg.role}`}
                >
                  <div
                    className={`rounded-2xl p-4 transition-all shadow-sm ${
                      isUser
                        ? "max-w-[85%] border border-ember-500/30 bg-ember-500/8 text-ink-100 rounded-tr-xs"
                        : "w-full border border-ink-800 bg-white glass text-ink-100 rounded-tl-xs"
                    }`}
                  >
                    {/* Header Label inside message */}
                    <div className="mb-2 flex items-center gap-2 text-[11px]">
                      {isUser ? (
                        <span className="font-semibold text-ember-300">You</span>
                      ) : (
                        <div className="flex items-center gap-1.5 font-semibold text-ember-300">
                          <BotIcon className="h-3.5 w-3.5 text-ember-400" />
                          <span>Ask Fleeting Assistant</span>
                        </div>
                      )}
                    </div>

                    {/* Formatted Message Body with clickable citations */}
                    {isUser ? (
                      <p className="text-[13.5px] leading-relaxed whitespace-pre-wrap text-ink-100 font-medium">
                        {msg.content}
                      </p>
                    ) : (
                      renderFormattedContent(msg.content, onOpenNote, onOpenTasks)
                    )}

                    {/* Pending destructive action — requires explicit approval */}
                    {!isUser && msg.pending_action && (
                      <div
                        data-testid="pending-action"
                        className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-ember-400/30 bg-ember-500/[0.07] px-3 py-2.5"
                      >
                        <span className="text-[12px] text-ember-200">
                          {msg.pending_action.summary}
                        </span>
                        <span className="flex-1" />
                        <button
                          type="button"
                          data-testid="cancel-action"
                          onClick={() => handleCancelAction(msg.id)}
                          disabled={loading}
                          className="rounded-lg border border-white/10 px-2.5 py-1 text-[11px] text-ink-300 transition-colors hover:bg-white/5 disabled:opacity-40 cursor-pointer"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          data-testid="confirm-action"
                          onClick={() => handleConfirmAction(msg)}
                          disabled={loading}
                          className="rounded-lg bg-ember-500/90 px-2.5 py-1 text-[11px] font-medium text-white transition-colors hover:bg-ember-500 disabled:opacity-40 cursor-pointer"
                        >
                          Confirm
                        </button>
                      </div>
                    )}

                    {/* Grounded Sources Tray */}
                    {!isUser && msg.sources && msg.sources.length > 0 && (
                      <div className="mt-3.5 pt-3 border-t border-white/[0.06] space-y-2">
                        <button
                          type="button"
                          onClick={() => toggleSources(msg.id)}
                          className="flex items-center gap-1.5 font-mono text-[11px] text-ink-400 hover:text-ink-200 transition-colors cursor-pointer"
                        >
                          <FolderIcon className="h-3 w-3 text-ink-500" />
                          <span className="font-medium">
                            Grounded Sources ({msg.sources.length})
                          </span>
                          {msg.context_used && (
                            <span className="text-ink-500 text-[10px]">
                              · {msg.context_used.notes_count} notes,{" "}
                              {msg.context_used.tasks_count} tasks,{" "}
                              {msg.context_used.logs_count} logs
                            </span>
                          )}
                          <span className="text-[10px] ml-1">
                            {isExpanded ? "▲" : "▼"}
                          </span>
                        </button>

                        {isExpanded && (
                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                            {msg.sources.map((s, sIdx) => {
                              const isClickable = s.kind === "note" || s.kind === "task";
                              return (
                                <div
                                  key={`src-${s.id}-${sIdx}`}
                                  onClick={() => {
                                    if (s.kind === "note") onOpenNote(s.id);
                                    else if (s.kind === "task") onOpenTasks?.();
                                  }}
                                  className={`rounded-xl border border-white/[0.05] bg-ink-950/60 p-2.5 transition-all ${
                                    isClickable
                                      ? "cursor-pointer hover:border-ember-400/40 hover:bg-ink-900/60"
                                      : ""
                                  }`}
                                  data-testid={`source-card-${s.id}`}
                                >
                                  <div className="flex items-center gap-1.5 mb-1">
                                    <span className="text-[11px]">
                                      {s.kind === "note" ? "📄" : s.kind === "task" ? "☑" : "🕒"}
                                    </span>
                                    <span className="font-semibold text-xs text-ink-200 truncate">
                                      {s.title}
                                    </span>
                                    <span className="ml-auto font-mono text-[9px] uppercase px-1.5 py-0.2 rounded bg-white/[0.05] text-ink-400 shrink-0">
                                      {s.kind}
                                    </span>
                                  </div>
                                  {s.snippet && (
                                    <p className="text-[11px] text-ink-400 line-clamp-2 leading-relaxed">
                                      {s.snippet}
                                    </p>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* In-Flight Thinking Indicator */}
            {loading && (
              <div
                className="flex items-start"
                data-testid="assistant-loading"
              >
                <div className="w-full max-w-xl rounded-2xl border border-ink-800 bg-white glass p-4 text-ink-100 rounded-tl-xs space-y-2">
                  <div className="flex items-center gap-2 text-[11px] font-semibold text-ember-300">
                    <BotIcon className="h-3.5 w-3.5 text-ember-400 animate-pulse" />
                    <span>Ask Fleeting Assistant</span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-ink-400">
                    <div className="flex gap-1">
                      <span className="h-1.5 w-1.5 rounded-full bg-ember-400 animate-bounce" />
                      <span className="h-1.5 w-1.5 rounded-full bg-ember-400 animate-bounce [animation-delay:0.2s]" />
                      <span className="h-1.5 w-1.5 rounded-full bg-ember-400 animate-bounce [animation-delay:0.4s]" />
                    </div>
                    <span>Consulting notes, tasks, and daily logs…</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Docked Query Input Bar */}
      <div className="app-toolbar shrink-0 border-t p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendPrompt(input);
          }}
          className="max-w-3xl mx-auto flex items-center gap-2"
        >
          <div className="relative flex-1">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about your notes, tasks, or recent activity…"
              disabled={loading}
              className="h-10 w-full rounded-xl border border-ink-800/90 bg-ink-950/90 px-4 text-xs text-ink-100 placeholder-ink-400 outline-none transition-colors focus:border-ember-500/50 disabled:opacity-60"
              data-testid="assistant-input"
            />
          </div>

          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="flex h-10 items-center justify-center gap-1.5 rounded-xl border border-ember-500/40 bg-ember-500/20 px-4 text-xs font-semibold text-ember-200 transition-all hover:bg-ember-500/30 hover:border-ember-400 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            data-testid="send-prompt-btn"
          >
            {loading ? (
              <span className="h-3.5 w-3.5 rounded-full border-2 border-ember-300 border-t-transparent animate-spin" />
            ) : (
              <SendIcon className="h-3.5 w-3.5 text-ember-300" />
            )}
            <span className="hidden sm:inline">Ask</span>
          </button>
        </form>
      </div>
    </div>
  );
}
