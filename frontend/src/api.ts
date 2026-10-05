import type {
  Note,
  Collection,
  Settings,
  Stats,
  TagCount,
  TaskItem,
  TaskPriority,
  RepoInfo,
  HealthStatus,
  ConnectionTest,
  LLMProbeOverrides,
  ActivityDay,
  ActivitySession,
  DailyLog,
  AppRule,
  FilesActivity,
  VaultSyncResult,
  SearchMode,
  AssistantChatIn,
  AssistantChatOut,
  AssistantSuggestionsOut,
  ProcessApp,
  ProcessInfo,
  ProcessDetails,
  WeeklyLogOut,
  UnifiedResult,
  WeeklyLogRow,

} from "./types";

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<HealthStatus>("/health"),

  /** Weekly digest plus the week's shape. Defaults to last week. */
  weeklyLog: (week?: string) =>
    req<WeeklyLogOut>(`/activity/weekly-log${week ? `?week=${week}` : ""}`),

  generateWeeklyLog: (week?: string) =>
    req<{ report: WeeklyLogRow; week: string }>("/activity/weekly-log/generate", {
      method: "POST",
      body: JSON.stringify({ week }),
    }),

  /** Kick off the embedding migration; returns immediately. */
  backfillEmbeddings: () =>
    req<{ started: boolean; reason?: string }>("/settings/embeddings/backfill", {
      method: "POST",
      body: JSON.stringify({}),
    }),

  notes: (params: Record<string, string> = {}) =>
    req<Note[]>(`/notes?${new URLSearchParams(params)}`),

  updateNote: (id: string, changes: Partial<Note>) =>
    req<Note>(`/notes/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),

  /** #274: DELETE trashes — reversible until purge or the retention window. */
  deleteNote: (id: string) => req<{ ok: boolean }>(`/notes/${id}`, { method: "DELETE" }),

  restoreNote: (id: string) => req<Note>(`/notes/${id}/restore`, { method: "POST" }),

  collections: () => req<Collection[]>("/collections"),

  noteCollections: (id: string) => req<Collection[]>(`/notes/${id}/collections`),

  createSamples: () => req<{ ok: boolean; created: number }>("/samples", { method: "POST" }),

  collection: (id: string) => req<Collection & { notes: Note[] }>(`/collections/${id}`),

  createCollection: (data: { name: string; kind?: string; description?: string; query?: Record<string, unknown> }) =>
    req<Collection>("/collections", { method: "POST", body: JSON.stringify(data) }),

  deleteCollection: (id: string) => req<{ ok: boolean }>(`/collections/${id}`, { method: "DELETE" }),

  addToCollection: (id: string, noteId: string) =>
    req<{ ok: boolean }>(`/collections/${id}/notes`, {
      method: "POST",
      body: JSON.stringify({ note_id: noteId }),
    }),

  removeFromCollection: (id: string, noteId: string) =>
    req<{ ok: boolean }>(`/collections/${id}/notes/${noteId}`, { method: "DELETE" }),

  noteLinks: (id: string) =>
    req<{ outgoing: Note[]; backlinks: Note[] }>(`/notes/${id}/links`),

  noteVersions: (id: string) =>
    req<
      { id: number; title: string; summary: string; raw_text: string; origin: string; created_at: string }[]
    >(`/notes/${id}/versions`),

  revertVersion: (id: string, versionId: number) =>
    req<Note>(`/notes/${id}/versions/${versionId}/revert`, { method: "POST" }),

  regenerateNote: (id: string, model?: string) =>
    req<Note>(`/notes/${id}/regenerate`, {
      method: "POST",
      body: JSON.stringify(model ? { model } : {}),
    }),

  purgeNote: (id: string) => req<{ ok: boolean }>(`/notes/${id}/purge`, { method: "POST" }),

  trash: () => req<Note[]>("/trash"),

  emptyTrash: () => req<{ ok: boolean; purged: number }>("/trash/empty", { method: "POST" }),

  archiveNote: (id: string) => req<Note>(`/notes/${id}/archive`, { method: "POST" }),
  pinNote: (id: string) => req<Note>(`/notes/${id}/pin`, { method: "POST" }),
  starNote: (id: string) => req<Note>(`/notes/${id}/star`, { method: "POST" }),
  snoozeNote: (id: string, until: string | null) =>
    req<Note>(`/notes/${id}/snooze`, { method: "POST", body: JSON.stringify({ until }) }),

  reprocess: (id: string) => req<Note>(`/notes/${id}/reprocess`, { method: "POST" }),

  exportNote: (id: string) =>
    req<{ ok: boolean; path: string }>(`/notes/${id}/export`, { method: "POST" }),

  captureText: (text: string, opts?: { template?: string; mode?: string }) =>
    req<Note>("/capture/text", { method: "POST", body: JSON.stringify({ text, ...opts }) }),

  captureYouTube: (url: string, opts?: { template?: string; mode?: string }) =>
    req<Note>("/capture/youtube", { method: "POST", body: JSON.stringify({ url, ...opts }) }),

  captureAudio: (blob: Blob, filename = "memo.webm", opts?: { template?: string; mode?: string; language?: string }) => {
    const fd = new FormData();
    fd.append("file", blob, filename);
    if (opts?.template) fd.append("template", opts.template);
    if (opts?.mode) fd.append("mode", opts.mode);
    if (opts?.language) fd.append("language", opts.language);
    return req<Note>("/capture/audio", { method: "POST", body: fd });
  },

  transcribePreview: (blob: Blob) => {
    const fd = new FormData();
    fd.append("file", blob, "snapshot.webm");
    return req<{ text: string }>("/capture/preview", { method: "POST", body: fd });
  },

  profiles: () => req<Record<string, { language?: string; template?: string; mode?: string }>>("/profiles"),

  templates: () => req<Record<string, { type?: string; tags?: string[]; prompt?: string; mode?: string }>>("/templates"),

  search: (
    q: string,
    params?: { mode?: SearchMode; type?: string; repo?: string; limit?: number }
  ) => {
    const searchParams = new URLSearchParams({ q });
    if (params?.mode) searchParams.set("mode", params.mode);
    if (params?.type && params.type !== "all") searchParams.set("type", params.type);
    if (params?.repo && params.repo !== "all") searchParams.set("repo", params.repo);
    if (params?.limit) searchParams.set("limit", String(params.limit));
    return req<Note[]>(`/search?${searchParams.toString()}`);
  },

  tags: () => req<TagCount[]>("/tags"),

  /** Notes + window sessions + commits. Additive to /search. */
  unifiedSearch: (q: string, params?: { limit?: number; since_day?: string }) => {
    const sp = new URLSearchParams({ q });
    if (params?.limit) sp.set("limit", String(params.limit));
    if (params?.since_day) sp.set("since_day", params.since_day);
    return req<UnifiedResult>(`/search/unified?${sp.toString()}`);
  },

  tasks: (
    params?:
      | boolean
      | {
          status?: string;
          priority?: string;
          repo?: string;
          due?: string;
          q?: string;
          limit?: number;
          offset?: number;
        }
  ) => {
    if (typeof params === "boolean") {
      return req<TaskItem[]>(`/tasks${params ? "?include_done=true" : ""}`);
    }
    if (!params) {
      return req<TaskItem[]>("/tasks");
    }
    const sp = new URLSearchParams();
    if (params.status) sp.set("status", params.status);
    if (params.priority) sp.set("priority", params.priority);
    if (params.repo) sp.set("repo", params.repo);
    if (params.due) sp.set("due", params.due);
    if (params.q) sp.set("q", params.q);
    if (params.limit !== undefined) sp.set("limit", String(params.limit));
    if (params.offset !== undefined) sp.set("offset", String(params.offset));
    const query = sp.toString();
    return req<TaskItem[]>(`/tasks${query ? `?${query}` : ""}`);
  },

  toggleTask: (id: string) => req<TaskItem>(`/tasks/${id}/toggle`, { method: "POST" }),

  updateTask: (id: string, data: Partial<TaskItem>) =>
    req<TaskItem>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  createTask: (data: {
    text: string;
    priority?: TaskPriority;
    due_date?: string | null;
    repo?: string | null;
    note_id?: string;
  }) => req<TaskItem>("/tasks", { method: "POST", body: JSON.stringify(data) }),

  deleteTask: (id: string) => req<{ ok: boolean; id: string }>(`/tasks/${id}`, { method: "DELETE" }),

  taskRepos: () => req<RepoInfo[]>("/tasks/repos"),

  stats: (days = 7) => req<Stats>(`/stats?days=${days}`),

  settings: () => req<Settings>("/settings"),

  resyncVault: () => req<VaultSyncResult>("/settings/vault/resync", { method: "POST" }),

  updateSettings: (changes: Record<string, unknown>) =>
    req<Settings>("/settings", { method: "PUT", body: JSON.stringify(changes) }),

  testLLM: (overrides?: LLMProbeOverrides) =>
    req<ConnectionTest>("/settings/test-llm", {
      method: "POST",
      body: overrides ? JSON.stringify(overrides) : undefined,
    }),

  testWhisper: () => req<ConnectionTest>("/settings/test-whisper", { method: "POST" }),

  activityDay: (day?: string) =>
    req<ActivityDay>(`/activity/day${day ? `?day=${day}` : ""}`),

  activityWeek: (days = 7) => req<{ day: string; seconds: number }[]>(`/activity/week?days=${days}`),

  liveSession: () => req<{ session: ActivitySession | null; paused: boolean }>("/activity/live"),

  pauseActivity: (paused: boolean) =>
    req<{ paused: boolean }>("/activity/pause", { method: "POST", body: JSON.stringify({ paused }) }),

  dailyLog: (day?: string) =>
    req<DailyLog>(`/activity/daily-log${day ? `?day=${day}` : ""}`),

  generateDailyLog: (day: string, rolling = false) =>
    req<DailyLog>("/activity/daily-log/generate", {
      method: "POST",
      body: JSON.stringify({ day, rolling }),
    }),

  knownApps: () => req<AppRule[]>("/activity/apps"),

  setAppTracked: (app_class: string, tracked: boolean) =>
    req<{ app_class: string; tracked: boolean }>("/activity/apps/tracked", {
      method: "POST",
      body: JSON.stringify({ app_class, tracked }),
    }),

  filesActivity: (hours = 24) =>
    req<FilesActivity>(`/activity/files?hours=${hours}`),

  assistantChat: (body: AssistantChatIn) =>
    req<AssistantChatOut>("/assistant/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Streaming variant: onDelta fires per chunk, resolves with the final done event. */
  assistantChatStream: async (
    body: AssistantChatIn,
    onDelta: (text: string) => void,
    signal?: AbortSignal,
  ): Promise<AssistantChatOut> => {
    const res = await fetch(BASE + "/assistant/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok || !res.body) {
      throw new Error(res.statusText || "stream request failed");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let final: AssistantChatOut | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith("data:")) continue;
        let evt: { type?: string; text?: string; detail?: string } & Partial<AssistantChatOut>;
        try {
          evt = JSON.parse(line.slice(5).trim());
        } catch {
          continue;
        }
        if (evt.type === "delta" && evt.text) onDelta(evt.text);
        else if (evt.type === "done") {
          final = {
            message: evt.message!,
            sources: evt.sources ?? [],
            context_used: evt.context_used ?? { notes_count: 0, tasks_count: 0, logs_count: 0 },
            pending_action: evt.pending_action ?? null,
          };
        } else if (evt.type === "error") {
          throw new Error(evt.detail || "stream error");
        }
      }
    }
    if (!final) throw new Error("stream ended without a final event");
    return final;
  },

  assistantSuggestions: () =>
    req<AssistantSuggestionsOut>("/assistant/suggestions"),

  processApps: () => req<ProcessApp[]>("/processes/apps"),

  processList: (params?: { sort_by?: string; limit?: number }) => {
    const sp = new URLSearchParams();
    if (params?.sort_by) sp.set("sort_by", params.sort_by);
    if (params?.limit) sp.set("limit", String(params.limit));
    const q = sp.toString();
    return req<ProcessInfo[]>(`/processes/list${q ? `?${q}` : ""}`);
  },

  processKill: (pid: number, force = false) =>
    req<{ ok: boolean; pid: number }>(`/processes/${pid}/kill${force ? "?force=true" : ""}`, { method: "POST" }),

  processDetails: (pid: number) => req<ProcessDetails>(`/processes/${pid}/details`),

  /** The user the backend runs as; decides which rows can be ended. */
  whoami: () => req<{ user: string }>("/processes/whoami"),
};
