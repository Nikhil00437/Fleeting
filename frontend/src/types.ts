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

export type TaskPriority = "P1" | "P2" | "P3";

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
  transcribe_model: string;
  transcribe_language: string;
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
  activity_excluded_apps: string;
  activity_auto_daily_log: boolean;
  activity_watch_dirs: string;
  activity_mirror_daily_log: boolean;
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
  model?: string;
}

export interface ActivitySession {
  id: number;
  app_class: string;
  title: string;
  first_seen: string;
  last_seen: string;
  seconds: number;
  day: string;
}

export interface ActivityApp {
  app: string;
  seconds: number;
  titles: { title: string; seconds: number }[];
}

export interface ActivityDay {
  day: string;
  paused: boolean;
  collector: { running: boolean; enabled: boolean; last_error: string | null };
  total_seconds: number;
  apps: ActivityApp[];
  sessions: ActivitySession[];
}

export interface DailyLog {
  day: string;
  summary_md: string | null;
  model: string | null;
  created_at: string | null;
}

export interface AppRule {
  app_class: string;
  seconds: number;
  sessions: number;
  last_day: string | null;
  tracked: boolean;
  has_rule: boolean;
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
}

declare global {
  interface Window {
    fleetingDesktop?: FleetingDesktopBridge;
  }
}

export type SearchMode = "hybrid" | "keyword" | "semantic";

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
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
}

export interface AssistantChatOut {
  message: ChatMessage;
  sources: SourceRef[];
  context_used: {
    notes_count: number;
    tasks_count: number;
    logs_count: number;
  };
}

export interface AssistantSuggestionsOut {
  suggestions: string[];
}

