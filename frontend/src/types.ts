export interface ActionItem {
  id: string;
  text: string;
  done: boolean;
}

export interface Note {
  id: string;
  type: string; // text | voice | youtube
  title: string;
  summary: string;
  raw_text: string;
  tags: string[];
  action_items: ActionItem[];
  source: Record<string, any>;
  audio_path: string | null;
  status: string; // pending | processing | done | failed
  error: string | null;
  pinned: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
  snippet?: string | null;
  score?: number;
  match_type?: SearchMode | "hybrid" | "keyword" | "semantic";
  feedback_down?: boolean; // #321: marked "not relevant" for the active query
  // 0.4 metadata
  starred?: boolean;
  trashed_at?: string | null;
  color?: string | null;
  fields?: Record<string, unknown>;
  sensitive?: boolean;
  review_state?: "raw" | "enriched" | "reviewed" | "final";
  snoozed_until?: string | null;
}

export interface Stats {
  total: number;
  today: number;
  week: number;
  open_tasks: number;
  done_tasks: number;
  queue: number;
  by_type?: {
    text: number;
    voice: number;
    youtube: number;
  };
  notes_per_day: { day: string; count: number }[];
}

export interface DayPoint {
  day: string;
  seconds?: number;
  count?: number;
}

export interface TagCount {
  tag: string;
  count: number;
}

/** One row of the query log (#322/#49). hits = last result count. */
export interface QueryLogEntry {
  q: string;
  hits: number;
  searched: number;
  last_at: string;
}

/** #111: one saved assistant conversation. */
export interface ChatHistoryItem {
  id: string;
  title: string;
  pinned: number;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
  hit_count: number;
  preview: string;
}

/** #319: a timestamped transcript match (t = seconds into the audio). */
export interface TranscriptHit {
  t: number;
  text: string;
}

export interface TranscriptResult {
  note: Note;
  hits: TranscriptHit[];
}

export type TaskPriority = "P1" | "P2" | "P3";

export type TaskList = "inbox" | "someday";

/** What the quick-add parser recognised in one line of text (#278). */
export interface QuickAddParsed {
  text: string;
  due_date: string | null;
  context: string | null;
  repo: string | null;
  priority: string | null;
}

export interface QuickAddResult {
  task: TaskItem;
  parsed: QuickAddParsed;
}

/** #30/#33: the Today view payload — buckets + next action + day load. */
export interface TodayLoad {
  estimated_min: number;
  spent_min: number;
  capacity_min: number;
}

export interface PlanDay {
  day: string;
  workday: boolean;
  capacity_min: number;
  planned_min: number;
  task_ids: string[];
}

export interface WeekPlan {
  week_start: string;
  days: PlanDay[];
  unscheduled: string[];
  totals: {
    capacity_min: number;
    planned_min: number;
    over_capacity: boolean;
    utilization: number;
  };
}

export interface StreakData {
  current_streak: number;
  best_streak: number;
  active_days: number;
  cells: Array<{ day: string; count: number }>;
}

export interface TodayData {
  day: string;
  overdue: TaskItem[];
  due_today: TaskItem[];
  waiting: TaskItem[];
  completed_today: TaskItem[];
  next_action: TaskItem | null;
  up_next: TaskItem[];
  load: TodayLoad;
  /** #39 completion streaks + heatmap. */
  streak?: StreakData | null;
}

export interface TaskItem {
  id: string;
  note_id: string;
  note_title?: string;
  text: string;
  done: boolean;
  priority: TaskPriority;
  due_date: string | null;
  repo: string | null;
  created_at: string;
  completed_at: string | null;
  /** 0.5 planning fields (backend v16). parent_id nests one level deep. */
  parent_id?: string | null;
  /** CSV of task ids this task is blocked by. */
  blocked_by?: string | null;
  estimate_min?: number | null;
  spent_min?: number | null;
  list?: TaskList;
  /** GTD context, stored without the leading @ ("home", "computer", …). */
  context?: string | null;
  waiting_for?: string | null;
  /** #31: "manual" means the user ranked it; inference never overwrites that. */
  priority_source?: "inferred" | "manual" | null;
  /** #34: the app/window this task can be done in. */
  app_hint?: string | null;
  follow_up_at?: string | null;
  recurrence?: string | null;
  sort_order?: number;
}

export interface TaskStats {
  total: number;
  open: number;
  done: number;
  completion_rate: number;
  by_priority: {
    P1: number;
    P2: number;
    P3: number;
  };
  overdue: number;
  due_today: number;
}

export interface RepoInfo {
  name: string;
  path?: string | null;
  task_count: number;
}

export interface TaskRef extends TaskItem {
  item_id?: string;
}

export interface HealthStatus {
  ok: boolean;
  version: string;
  uptime_secs: number;
  db: boolean;
  whisper_loaded: boolean;
  queue: number;
  /** Model actually used for embeddings; "local-hash-384" means offline fallback. */
  embedding_model?: string;
  semantic_search?: "semantic" | "lexical";
  /** Notes still on an older embedding model, invisible to semantic search. */
  stale_embeddings?: number;
  /** Human-readable reasons the app is running in a reduced mode. */
  degradations?: string[];
}

export interface WhisperProgress {
  status: "idle" | "downloading" | "loading" | "ready" | "error";
  model: string;
  percent: number;
  downloaded_bytes: number;
  total_bytes: number;
  speed_bps: number;
  detail: string;
}

export interface Settings {
  host: string;
  port: number;
  vault_dir: string;
  vault_sync: boolean;
  vault_writable: boolean;
  llm_provider: string;
  llm_base_url: string;
  llm_model: string;
  llm_timeout_secs: number;
  /** Whether an API key is stored. The key itself is never returned by the API. */
  llm_api_key_set?: boolean;
  transcribe_model: string;
  transcribe_language: string;
  transcribe_vocabulary?: string;
  transcribe_translate?: boolean;
  transcribe_cleanup_audio?: boolean;
  transcribe_keep_audio?: boolean;
  transcribe_voice_punctuation?: boolean;
  transcribe_auto_format?: boolean;
  transcribe_replacements?: string;
  transcribe_diarize?: boolean;
  transcribe_hf_token_set?: boolean;
  transcribe_loaded: boolean;
  transcribe_cached_models?: string[];
  transcribe_progress?: WhisperProgress;
  yt_transcribe_fallback: boolean;
  yt_max_duration_min: number;
  desktop_notifications: boolean;
  activity_enabled: boolean;
  activity_paused: boolean;
  activity_poll_secs: number;
  activity_idle_after_min: number;
  /** #60 auto | logind | cursor */
  activity_idle_source: string;
  /** Whether logind's idle property is readable on this host. */
  activity_idle_available: boolean;
  activity_excluded_apps: string;
  activity_auto_daily_log: boolean;
  activity_auto_weekly_log: boolean;
  activity_watch_dirs: string;
  activity_mirror_daily_log: boolean;
  /** Days of window-activity history kept; older rows pruned on startup. */
  activity_retention_days: number;
  activity_running: boolean;
  config_path: string;
}

export interface VaultSyncResult {
  ok: boolean;
  synced_notes: number;
  imported_notes: number;
  tasks_updated: number;
}

export interface ConnectionTest {
  ok: boolean;
  detail?: string;
  models?: string[];
  /** Models the server reported that cannot be used for chat (embedding-only). */
  hidden?: number;
  model?: string;
}

export interface LLMProbeOverrides {
  provider?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
}

/** #63 the answer to "what was I doing in this stretch?". */
export interface WindowAnswer {
  day: string;
  start: string;
  end: string;
  question: string;
  answer: string;
  used_llm: boolean;
  sessions: {
    id: number;
    app_class: string;
    title: string;
    first_seen: string;
    last_seen: string;
    seconds: number;
    project: string | null;
    note: string | null;
  }[];
}

/** #58 context switches for a day. */
export interface SwitchMetrics {
  day: string;
  switches: number;
  reasons: { app: number; gap: number; project: number };
  sessions: number;
  seconds_per_switch: number | null;
}

/** #62 today's total against the mean of the previous days. */
export interface TodayVsAverage {
  day: string;
  seconds: number;
  average_seconds: number;
  delta_seconds: number;
  pct: number | null;
  window: number;
  days_tracked: number;
}

export interface HeatmapCell {
  day: string;
  minutes: number;
}

/** #59 calendar grid of active minutes. */
export interface HeatmapData {
  from: string;
  to: string;
  weeks: number;
  cells: HeatmapCell[];
  peak_minutes: number;
}

/** #339 one entry in the merged day feed. */
export interface DayEvent {
  kind: "session" | "task" | "note";
  id: string | number;
  at: string;
  label: string;
  detail?: string;
  seconds?: number;
  done?: boolean;
}

/** #337 an untracked stretch of the day. */
export interface ActivityGap {
  start: string;
  end: string;
  minutes: number;
}

export interface ActivitySession {
  id: number;
  app_class: string;
  title: string;
  first_seen: string;
  last_seen: string;
  seconds: number;
  day: string;
  workspace?: string | null;
  project?: string | null;
  branch?: string | null;
  /** #334 what this stretch was actually for. */
  note?: string | null;
}

export interface ActivityApp {
  app: string;
  seconds: number;
  titles: { title: string; seconds: number }[];
}

export interface ActivityDay {
  day: string;
  paused: boolean;
  /** #65 set while private mode is running. */
  private_until?: string | null;
  collector: { running: boolean; enabled: boolean; last_error: string | null };
  total_seconds: number;
  apps: ActivityApp[];
  sessions: ActivitySession[];
}

export interface ReportEvidenceSession {
  id?: number;
  app: string;
  title: string;
  seconds: number;
  start: string;
  end: string;
}

export interface ReportEvidenceNote {
  id: string;
  title: string;
}

export interface ReportEvidenceCommit {
  repo: string;
  subject: string;
}

export interface ReportEvidenceItem {
  section: string;
  text: string;
  sessions: ReportEvidenceSession[];
  notes: ReportEvidenceNote[];
  commits: ReportEvidenceCommit[];
}

export interface DailyLog {
  day: string;
  summary_md: string | null;
  edited_body?: string | null;
  edited?: number;
  model: string | null;
  created_at: string | null;
  evidence?: ReportEvidenceItem[];
}

export interface AppRule {
  app_class: string;
  seconds: number;
  sessions: number;
  last_day: string | null;
  tracked: boolean;
  has_rule: boolean;
  /** #340 per-app idle threshold in minutes; null = use the global setting. */
  idle_min?: number | null;
}

export interface FilesActivity {
  since: string;
  total: number;
  groups: { label: string; count: number; exts: [string, number][]; samples: string[] }[];
  git: { repo: string; subjects: string[] }[];
}

export interface FleetingDesktopBridge {
  isElectron: boolean;
  platform: string;
  minimize: () => Promise<void>;
  toggleMaximize: () => Promise<boolean>;
  close: () => Promise<void>;
  isMaximized: () => Promise<boolean>;
  openExternal: (url: string) => Promise<void>;
  onMaximizeChange: (cb: (maximized: boolean) => void) => () => void;
  onNavigate: (cb: (target: string) => void) => () => void;
  hideHud?: () => Promise<void>;
  resizeHud?: (height: number) => Promise<void>;
  typeText?: (text: string) => Promise<boolean>;
  onHudTrigger?: (cb: () => void) => () => void;
  undoLastType?: () => Promise<boolean>;
  activeAppClass?: () => Promise<string | null>;
  activeWindow?: () => Promise<{ app: string | null; title: string | null }>;
}

declare global {
  interface Window {
    fleetingDesktop?: FleetingDesktopBridge;
  }
}

export type SearchMode = "hybrid" | "keyword" | "semantic";

export interface TemplateFieldDef {
  name: string;
  type: "text" | "number" | "rating" | "status" | "url" | "date" | "cost";
  options?: string[];
}

export interface Collection {
  id: string;
  kind: "manual" | "saved_query" | "project";
  name: string;
  description: string;
  status: string | null;
  query: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  item_count?: number;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  /** Citations, persisted with the transcript (#111). */
  sources?: SourceRef[];
}

export interface SourceRef {
  id: string;
  title: string;
  type: string;
  kind: "note" | "task" | "log";
  snippet?: string;
}

export interface AssistantChatIn {
  messages: ChatMessage[];
  repo?: string | null;
  type?: string | null;
  confirm?: boolean;
}

export interface PendingAction {
  tool: string;
  params: Record<string, unknown>;
  summary: string;
}

export interface AssistantChatOut {
  message: ChatMessage;
  sources: SourceRef[];
  context_used: {
    notes_count: number;
    tasks_count: number;
    logs_count: number;
  };
  pending_action?: PendingAction | null;
}

export interface AssistantSuggestionsOut {
  suggestions: string[];
}

export interface ProcessApp {
  pid: number;
  name: string;
  cpu_percent: number;
  memory_mb: number;
  status: string;
  window_title: string | null;
  /** Owner, as returned by the API; decides whether End is offered. */
  username: string;
}

export interface ProcessInfo {
  pid: number;
  name: string;
  username: string;
  cpu_percent: number;
  memory_mb: number;
  status: string;
  command: string;
  created: string;
}

export interface ProcessDetails extends ProcessInfo {
  num_threads: number;
  open_files_count: number;
  connections_count: number;
  parent_pid: number | null;
  children: number[];
}

export interface WeekDayRow {
  day: string;
  seconds: number;
  busy: boolean;
}

export interface WeekAppRow {
  app_class: string;
  seconds: number;
}

export interface WeekSummary {
  week_start: string;
  week_end: string;
  days: WeekDayRow[];
  apps: WeekAppRow[];
  total_seconds: number;
  busiest_day: string | null;
  quietest_day: string | null;
  daily_logs: { day: string; summary_md: string; model: string | null }[];
  total_tasks: number;
  open_tasks: number;
  commits: { repo?: string; subject?: string }[];
  files_touched: number;
  diff?: WeeklyDiff;
}

export interface WeeklyDiff {
  current_week: string;
  previous_week: string;
  current_seconds: number;
  previous_seconds: number;
  delta_seconds: number;
  delta_pct: number | null;
  current_active_days: number;
  previous_active_days: number;
  app_shifts: {
    app_class: string;
    delta_seconds: number;
    current_seconds: number;
    previous_seconds: number;
  }[];
  narrative: string;
}

export interface WeeklyLogRow {
  week_start: string;
  summary_md: string;
  model: string | null;
  created_at: string;
}

export interface WeeklyLogOut {
  week: string;
  this_week: string;
  report: WeeklyLogRow | null;
  summary: WeekSummary;
  diff?: WeeklyDiff;
}

export interface UnifiedResult {
  query?: string;
  notes: Note[];
  sessions: { id: number; app_class: string; title: string; day: string; seconds: number }[];
  commits: { repo: string; subject: string; author: string | null; committed_at: string }[];
  counts?: { notes: number; sessions: number; commits: number };
  total: number;
}

export interface StandupOut {
  day: string;
  previous_day: string;
  standup_md: string;
  model: string;
  yesterday_tasks: TaskItem[];
  today_tasks: TaskItem[];
  blockers: TaskItem[];
}

export interface PeriodicReviewOut {
  kind: "month" | "quarter" | "year";
  period: string;
  start_date: string;
  end_date: string;
  title: string;
  review_md: string;
  model: string;
  metrics: {
    total_seconds: number;
    active_days: number;
    busiest_day: string | null;
    weekly_logs_count: number;
    daily_logs_count: number;
    completed_tasks_count: number;
    top_apps: { app_class: string; seconds: number }[];
  };
}

export interface UnfinishedThread {
  id: string;
  text: string;
  source_day: string;
  source_type: "daily_log" | "task";
  task_id?: string;
  created_at: string;
  age_days: number;
  waiting_for?: string | null;
  blocked_by?: string | null;
}

export interface ReportPlaygroundResult {
  day: string;
  system_prompt: string;
  transcript: string;
  preview_md: string;
  model: string;
}

export interface CaptureFrequencyStats {
  days: number;
  total_captures: number;
  avg_per_day: number;
  busiest_day: { day: string; count: number } | null;
  peak_hour: number | null;
  notes_per_day: {
    day: string;
    count: number;
    text: number;
    voice: number;
    youtube: number;
  }[];
  by_dow: { name: string; index: number; count: number }[];
  by_hour: { hour: number; count: number }[];
  top_tags_over_time: {
    tag: string;
    total: number;
    timeline: { day: string; count: number }[];
  }[];
}


