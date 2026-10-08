import type {
  Note,
  Collection,
  TemplateFieldDef,
  Settings,
  Stats,
  TagCount,
  TaskItem,
  TaskPriority,
  QuickAddResult,
  TodayData,
  WeekPlan,
  RepoInfo,
  HealthStatus,
  ConnectionTest,
  LLMProbeOverrides,
  ActivityDay,
  ActivitySession,
  ActivityGap,
  DayEvent,
  HeatmapData,
  SwitchMetrics,
  TodayVsAverage,
  WindowAnswer,
  DailyLog,
  AppRule,
  FilesActivity,
  VaultSyncResult,
  SearchMode,
  AssistantChatIn,
  AssistantChatOut,
  ChatHistoryItem,
  ChatMessage,
  AssistantSuggestionsOut,
  ProcessApp,
  ProcessInfo,
  ProcessDetails,
  WeeklyLogOut,
  UnifiedResult,
  WeeklyLogRow,
  QueryLogEntry,
  TranscriptResult,

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

  filingRules: () =>
    req<
      { id: number; match_field: string; match_value: string; action: string; action_value: string | null; enabled: number }[]
    >("/rules"),

  createFilingRule: (data: { match_field: string; match_value: string; action: string; action_value?: string | null }) =>
    req<{ id: number }>("/rules", { method: "POST", body: JSON.stringify(data) }),

  deleteFilingRule: (id: number) => req<{ ok: boolean }>(`/rules/${id}`, { method: "DELETE" }),

  runFilingRules: () => req<{ ok: boolean; changed: number }>("/rules/run", { method: "POST" }),

  cleanupSuggestions: () =>
    req<
      { kind: "archive" | "add_tag" | "rename" | "merge"; note_id: string; title: string; reason: string; value?: string; extra_note_ids?: string[] }[]
    >("/cleanup"),

  applyCleanup: (noteId: string, action: "archive" | "add_tag", value?: string) =>
    req<{ ok: boolean }>("/cleanup/apply", {
      method: "POST",
      body: JSON.stringify({ note_id: noteId, action, value }),
    }),

  createSamples: () => req<{ ok: boolean; created: number }>("/samples", { method: "POST" }),

  attachments: (noteId: string) =>
    req<{ id: string; filename: string; size: number; mime: string | null; created_at: string }[]>(
      `/notes/${noteId}/attachments`,
    ),

  uploadAttachment: (noteId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ id: string; filename: string }>(`/notes/${noteId}/attachments`, {
      method: "POST",
      body: fd,
    });
  },

  deleteAttachment: (noteId: string, attId: string) =>
    req<{ ok: boolean }>(`/notes/${noteId}/attachments/${attId}`, { method: "DELETE" }),

  attachmentUrl: (noteId: string, attId: string) => `/api/notes/${noteId}/attachments/${attId}/file`,

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

  /** #320/#23: nearest notes by embedding cosine (drawer related strip). */
  similarNotes: (id: string, limit = 8) =>
    req<Note[]>(`/notes/${id}/similar?limit=${limit}`),

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

  templates: () =>
    req<Record<string, { type?: string; tags?: string[]; prompt?: string; mode?: string; fields?: TemplateFieldDef[] }>>("/templates"),

  search: (
    q: string,
    params?: { mode?: SearchMode; type?: string; repo?: string; limit?: number; alpha?: number }
  ) => {
    const searchParams = new URLSearchParams({ q });
    if (params?.mode) searchParams.set("mode", params.mode);
    if (params?.type && params.type !== "all") searchParams.set("type", params.type);
    if (params?.repo && params.repo !== "all") searchParams.set("repo", params.repo);
    if (params?.limit) searchParams.set("limit", String(params.limit));
    // #315: hybrid RRF keyword weight; 1 = FTS only, 0 = vectors only.
    if (params?.alpha !== undefined) searchParams.set("alpha", String(params.alpha));
    return req<Note[]>(`/search?${searchParams.toString()}`);
  },

  tags: () => req<TagCount[]>("/tags"),

  /** #50 tag manager mutations. */
  renameTag: (fromTag: string, to: string) =>
    req<{ ok: boolean; updated: number }>("/tags/rename", {
      method: "POST",
      body: JSON.stringify({ from_tag: fromTag, to }),
    }),

  mergeTags: (fromTags: string[], to: string) =>
    req<{ ok: boolean; updated: number }>("/tags/merge", {
      method: "POST",
      body: JSON.stringify({ from_tags: fromTags, to }),
    }),

  deleteTag: (tag: string) =>
    req<{ ok: boolean; updated: number }>("/tags/delete", {
      method: "POST",
      body: JSON.stringify({ tag }),
    }),

  /** #425: rare / overlapping / misspelt tag candidates. */
  tagsAudit: () =>
    req<{
      rare: { tag: string; count: number }[];
      overlapping: { tags: string[]; target: string }[];
      misspelt: { tags: string[]; target: string }[];
    }>("/tags/audit"),

  /** #49/#322: recent + most-searched queries in one round trip. */
  searchHistory: () =>
    req<{ recent: QueryLogEntry[]; top: QueryLogEntry[] }>("/search/history"),

  /** #111 conversation history: list/search, upsert the thread, pin, delete. */
  chatHistory: (q = "") =>
    req<ChatHistoryItem[]>(`/assistant/history${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  saveChatHistory: (chatId: string, messages: ChatMessage[]) =>
    req<ChatHistoryItem>(`/assistant/history/${chatId}`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    }),
  pinChat: (chatId: string, pinned: boolean) =>
    req<ChatHistoryItem>(`/assistant/history/${chatId}`, {
      method: "PATCH",
      body: JSON.stringify({ pinned }),
    }),
  deleteChat: (chatId: string) =>
    req<void>(`/assistant/history/${chatId}`, { method: "DELETE" }),

  /** #319: voice-note transcripts with word-timestamp hits. */
  transcriptSearch: (q: string, limit = 6) => {
    const sp = new URLSearchParams({ q, limit: String(limit) });
    return req<TranscriptResult[]>(`/search/transcript?${sp.toString()}`);
  },

  /** #321 "not relevant" — down=false undoes the mark. */
  searchFeedback: (noteId: string, query: string, down: boolean) =>
    req<{ ok: boolean }>(`/search/feedback`, {
      method: "POST",
      body: JSON.stringify({ note_id: noteId, query, down }),
    }),

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
          list?: string;
          context?: string;
          waiting?: boolean;
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
    if (params.list) sp.set("list", params.list);
    if (params.context) sp.set("context", params.context);
    if (params.waiting !== undefined) sp.set("waiting", String(params.waiting));
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
    parent_id?: string;
    list?: "inbox" | "someday";
  }) => req<TaskItem>("/tasks", { method: "POST", body: JSON.stringify(data) }),

  /** #278 natural-language quick-add; explicit fields override parsed ones. */
  quickAdd: (data: {
    text: string;
    priority?: TaskPriority | null;
    due_date?: string | null;
    repo?: string | null;
    context?: string | null;
    note_id?: string;
    list?: "inbox" | "someday";
  }) => req<QuickAddResult>("/tasks/quick-add", { method: "POST", body: JSON.stringify(data) }),

  /** #30/#33: Today buckets, next action and day load from one ranking. */
  today: () => req<TodayData>("/tasks/today"),

  /** #46/#47/#297 resurfacing. `roll` re-rolls the random draw. */
  recall: (kind: "random" | "this_day" | "capsule", roll = 0) => {
    const sp = new URLSearchParams({ kind });
    if (kind === "random" && roll) sp.set("seed", String(roll * 7919 + 13));
    return req<Note[]>(`/recall?${sp.toString()}`);
  },

  /** #280: add real minutes spent on a task (focus timer). */
  logFocus: (id: string, minutes: number) =>
    req<TaskItem>(`/tasks/${id}/focus`, { method: "POST", body: JSON.stringify({ minutes }) }),

  weekPlan: () => req<WeekPlan>("/tasks/plan"),

  /** #38 weekly review input: slipped / due this week / closed. */
  /** #40: render tasks as todo.txt or a Markdown checklist (also files it in the vault). */
  exportTasks: (format: "todo" | "markdown" = "markdown") =>
    req<{ content: string; filename: string; path: string | null }>("/tasks/export", {
      method: "POST",
      body: JSON.stringify({ format }),
    }),

  /** #422: single-use tags, untagged notes, unlinked tasks. */
  orphans: () =>
    req<{
      single_use_tags: string[];
      untagged_notes: { id: string; title: string }[];
      unlinked_tasks: { id: string; text: string }[];
    }>("/orphans"),

  weeklyReview: () =>
    req<{
      week_start: string;
      today: string;
      carry_over: TaskItem[];
      this_week: TaskItem[];
      completed: TaskItem[];
      stats: { carry_over: number; this_week: number; completed: number; completion_rate: number };
    }>("/tasks/review"),

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

  /** #65 private mode from the UI as well as the tray. */
  privateState: () => req<{ active: boolean; until: string | null }>("/activity/private"),
  startPrivate: (minutes: number) =>
    req<{ active: boolean; until: string }>("/activity/private", {
      method: "POST",
      body: JSON.stringify({ minutes }),
    }),
  stopPrivate: () => req<void>("/activity/private", { method: "DELETE" }),

  activityDay: (day?: string) =>
    req<ActivityDay>(`/activity/day${day ? `?day=${day}` : ""}`),

  /** #53 time per project for a day. */
  activityProjects: (day?: string) =>
    req<{ day: string; projects: { project: string | null; seconds: number }[] }>(
      `/activity/projects${day ? `?day=${day}` : ""}`,
    ),

  /** #54 manual session editing. */
  relabelSession: (id: number, title: string) =>
    req<ActivitySession>(`/activity/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  splitSession: (id: number, at: string) =>
    req<ActivitySession[]>(`/activity/sessions/${id}/split`, {
      method: "POST",
      body: JSON.stringify({ at }),
    }),
  mergeSessions: (ids: number[]) =>
    req<ActivitySession>("/activity/sessions/merge", {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),
  deleteSession: (id: number) =>
    req<void>(`/activity/sessions/${id}`, { method: "DELETE" }),

  /** #334 annotate a session. */
  annotateSession: (id: number, note: string) =>
    req<ActivitySession>(`/activity/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ note }),
    }),

  /** #63 ask about a stretch of the timeline. */
  askWindow: (day: string, start: string, end: string, question = "") =>
    req<WindowAnswer>("/activity/ask", {
      method: "POST",
      body: JSON.stringify({ day, start, end, question }),
    }),

  /** #58 context switches, #62 today vs average, #59 calendar heatmap. */
  activitySwitches: (day?: string) =>
    req<SwitchMetrics>(`/activity/metrics/switches${day ? `?day=${day}` : ""}`),
  activityCompare: (day?: string, window = 7) =>
    req<TodayVsAverage>(
      `/activity/metrics/compare${new URLSearchParams({ ...(day ? { day } : {}), window: String(window) }).toString()}`,
    ),
  activityHeatmap: (weeks = 12, end?: string) =>
    req<HeatmapData>(
      `/activity/metrics/heatmap${new URLSearchParams({ weeks: String(weeks), ...(end ? { end } : {}) }).toString()}`,
    ),

  /** #342 session rows or a day×project timesheet, as CSV. */
  activityExportUrl: (format: "csv" | "timesheet", params: { day?: string; day_from?: string; day_to?: string }) => {
    const sp = new URLSearchParams({ format });
    for (const [k, v] of Object.entries(params)) if (v) sp.set(k, v);
    return `/api/activity/export?${sp.toString()}`;
  },

  /** #339 what you did, finished and wrote, in one feed. */
  activityTimeline: (day?: string, kinds = "session,task,note") =>
    req<{ day: string; events: DayEvent[] }>(
      `/activity/timeline?${new URLSearchParams({ ...(day ? { day } : {}), kinds }).toString()}`,
    ),

  /** #337 untracked stretches of a day, and what you did in one. */
  activityGaps: (day?: string) =>
    req<{ day: string; gaps: ActivityGap[]; summary: string }>(
      `/activity/gaps${day ? `?day=${day}` : ""}`,
    ),
  fillGap: (at: string, minutes: number, note: string) =>
    req<ActivitySession>("/activity/gaps/fill", {
      method: "POST",
      body: JSON.stringify({ at, minutes, note }),
    }),

  activityWeek: (days = 7) => req<{ day: string; seconds: number }[]>(`/activity/week?days=${days}`),

  liveSession: () => req<{ session: ActivitySession | null; paused: boolean }>("/activity/live"),

  pauseActivity: (paused: boolean) =>
    req<{ paused: boolean }>("/activity/pause", { method: "POST", body: JSON.stringify({ paused }) }),

  dailyLog: (day?: string) =>
    req<DailyLog>(`/activity/daily-log${day ? `?day=${day}` : ""}`),

  editDailyLog: (day: string, body: string) =>
    req<{ ok?: boolean; edited?: number; body?: string }>(`/activity/daily-log/${day}/edit`, {
      method: "PUT",
      body: JSON.stringify({ body }),
    }),

  clearDailyLogEdit: (day: string) =>
    req<void>(`/activity/daily-log/${day}/edit`, {
      method: "DELETE",
    }),

  generateDailyLog: (day: string, rolling = false) =>
    req<DailyLog>("/activity/daily-log/generate", {
      method: "POST",
      body: JSON.stringify({ day, rolling }),
    }),

  knownApps: () => req<AppRule[]>("/activity/apps"),

  /** #64 rename/merge app classes (rewrites their history). */
  appAliases: () => req<{ from_class: string; to_class: string }[]>("/activity/apps/aliases"),
  setAppAlias: (from_class: string, to_class: string) =>
    req<{ ok: boolean }>("/activity/apps/alias", {
      method: "POST",
      body: JSON.stringify({ from_class, to_class }),
    }),
  /** #340 per-app idle threshold. */
  appIdleRules: () => req<{ app_class: string; idle_min: number }[]>("/activity/apps/idle"),
  setAppIdle: (app_class: string, idle_min: number) =>
    req<{ ok: boolean }>("/activity/apps/idle", {
      method: "POST",
      body: JSON.stringify({ app_class, idle_min }),
    }),
  clearAppIdle: (app_class: string) =>
    req<void>(`/activity/apps/idle/${encodeURIComponent(app_class)}`, { method: "DELETE" }),
  deleteAppAlias: (from_class: string) =>
    req<void>(`/activity/apps/alias/${encodeURIComponent(from_class)}`, { method: "DELETE" }),

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
