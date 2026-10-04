import { fmtDuration, relTime, timeOfDay } from "../time";
import {
  CheckIcon,
  LinkIcon,
  MicIcon,
  PinIcon,
  RefreshIcon,
  SparkIcon,
  TextIcon,
  TrashIcon,
} from "./Icons";
import { activationProps } from "./a11y";
import type { Note } from "../types";

const TYPE_META: Record<
  string,
  {
    icon: React.ReactNode;
    label: string;
    pillCls: string;
    glow: string;
    accent: string;
  }
> = {
  text: {
    icon: <TextIcon className="h-3 w-3" />,
    label: "Note",
    pillCls: "bg-ember-500/12 text-ember-300 ring-1 ring-ember-400/25",
    glow: "radial-gradient(220px circle at 0% 0%, rgba(59, 130, 246, 0.08), transparent 70%)",
    accent: "#3b82f6",
  },
  voice: {
    icon: <MicIcon className="h-3 w-3" />,
    label: "Voice",
    pillCls: "bg-iris-500/15 text-iris-300 ring-1 ring-iris-400/25",
    glow: "radial-gradient(220px circle at 0% 0%, rgba(139, 92, 246, 0.08), transparent 70%)",
    accent: "#8b5cf6",
  },
  youtube: {
    icon: <LinkIcon className="h-3 w-3" />,
    label: "YouTube",
    pillCls: "bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-400/25",
    glow: "radial-gradient(220px circle at 0% 0%, rgba(6, 182, 212, 0.08), transparent 70%)",
    accent: "#06b6d4",
  },
};

export function StatusBadge({ note }: { note: Note }) {
  if (note.status === "done") return null;
  if (note.status === "failed")
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-red-500/12 px-2 py-0.5 text-[10.5px] font-medium text-red-300">
        <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
        Failed
      </span>
    );
  const stage = note.source?.stage;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ember-500/30 bg-ember-500/12 px-2 py-0.5 text-[10.5px] font-medium text-ember-300">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ember-400" />
      {stage ?? note.status}
    </span>
  );
}

interface Props {
  note: Note;
  onOpen: (id: string) => void;
  onPin: (id: string) => void;
  onTagClick?: (tag: string) => void;
  onToggleTask?: (note: Note, itemId: string) => void;
  onRetry?: (id: string) => void;
  onDelete?: (id: string) => void;
  highlight?: boolean;
}

export default function NoteCard({
  note,
  onOpen,
  onPin,
  onTagClick,
  onToggleTask,
  onRetry,
  onDelete,
  highlight,
}: Props) {
  const body = note.snippet ?? note.summary ?? note.raw_text ?? "";
  const parts = note.snippet ? note.snippet.split(/\[\[|\]\]/) : null;
  const meta = TYPE_META[note.type] ?? {
    icon: <SparkIcon className="h-3 w-3" />,
    label: note.type,
    pillCls: "bg-ink-800 text-ink-300 ring-1 ring-white/10",
    glow: "none",
    accent: "#d8784c",
  };

  const src = note.source ?? {};
  const voiceDur = src.transcription?.duration;
  const voiceLang = src.transcription?.language;
  const ytChannel = src.channel;
  const ytDuration = src.duration;
  const ytThumb = src.thumbnail;

  const openTasks = note.action_items.filter((it) => !it.done);
  const doneTasks = note.action_items.filter((it) => it.done);

  const isNew = Date.now() - new Date(note.created_at).getTime() < 5 * 60 * 1000;

  return (
    <article
      onClick={() => onOpen(note.id)}
      {...activationProps(
        `Open note: ${note.title || note.raw_text.slice(0, 60) || note.id}`,
        () => onOpen(note.id),
      )}
      className={`glass card-hover reveal group relative flex flex-col justify-between overflow-hidden rounded-2xl p-4 cursor-pointer ${
        highlight
          ? "!border-ember-400/50 ring-1 ring-ember-400/25"
          : ""
      }`}
      style={{ backgroundImage: meta.glow, borderLeftWidth: '3px', borderLeftColor: meta.accent }}
    >
      <div>
        {/* Top Meta Header Row */}
        <div className="mb-2.5 flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-[11px] font-medium ${meta.pillCls}`}
          >
            {meta.icon}
            <span>{meta.label}</span>
          </span>

          {/* Rich Type Metadata Pill */}
          {note.type === "voice" && voiceDur ? (
            <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-ink-300">
              {fmtDuration(voiceDur)}
              {voiceLang ? ` · ${String(voiceLang).toUpperCase()}` : ""}
            </span>
          ) : null}

          {note.type === "youtube" && (ytChannel || ytDuration) ? (
            <span className="truncate rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10.5px] font-medium text-cyan-200/90">
              {ytChannel}
              {ytDuration ? ` · ${fmtDuration(ytDuration)}` : ""}
            </span>
          ) : null}

          {note.status !== "done" && <StatusBadge note={note} />}

          {(note.score !== undefined || note.match_type) && (
            <span
              className="inline-flex items-center gap-1 rounded-md border border-amber-500/25 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] font-medium text-amber-300"
              title={
                note.score !== undefined
                  ? `Match score: ${(note.score * 100).toFixed(1)}%`
                  : undefined
              }
            >
              <SparkIcon className="h-2.5 w-2.5 text-amber-400" />
              {note.score !== undefined ? (
                <span>{Math.round(note.score <= 1 ? note.score * 100 : note.score)}% match</span>
              ) : null}
              {note.match_type && (
                <span className="text-[9px] text-amber-400/80 capitalize">
                  {note.score !== undefined ? `· ${note.match_type}` : `${note.match_type} match`}
                </span>
              )}
            </span>
          )}

          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            <div className="flex items-center">
              {isNew && <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-ember-500 pulse-dot" title="New" />}
              <span
                className="font-mono text-[10.5px] tabular-nums text-ink-400"
                title={timeOfDay(note.created_at)}
              >
                {relTime(note.created_at)}
              </span>
            </div>

            {note.status === "failed" && onRetry && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onRetry(note.id);
                }}
                className="rounded-md border border-white/10 bg-white/[0.05] px-1.5 py-0.5 text-[10px] font-medium text-ink-200 transition-colors hover:border-ember-400/40 hover:text-ember-300"
                title="Retry processing"
              >
                <RefreshIcon className="h-3 w-3" />
              </button>
            )}

            {note.status === "failed" && onDelete && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(note.id);
                }}
                className="rounded-md border border-red-500/20 bg-red-500/10 px-1.5 py-0.5 text-[10px] font-medium text-red-300 transition-colors hover:bg-red-500/20"
                title="Delete failed capture"
              >
                <TrashIcon className="h-3 w-3" />
              </button>
            )}

            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onPin(note.id);
              }}
              className={`rounded-lg p-1 transition-colors ${
                note.pinned
                  ? "text-ember-400"
                  : "text-ink-500 opacity-0 group-hover:opacity-100 hover:bg-white/[0.06] hover:text-ink-100"
              }`}
              title={note.pinned ? "Unpin note" : "Pin note"}
            >
              <PinIcon filled={note.pinned} className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Title + Optional YouTube Thumbnail Layout */}
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h3 className="line-clamp-1 text-[14px] font-semibold tracking-tight text-ink-100 transition-colors group-hover:text-ember-200">
              {note.title ||
                (note.raw_text ? note.raw_text.slice(0, 65) : "Untitled capture")}
            </h3>

            {note.status === "failed" && note.error && (
              <p className="mt-1 line-clamp-2 text-xs text-red-300/85">{note.error}</p>
            )}

            {note.status === "done" && body && (
              <p className="mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-ink-300">
                {parts
                  ? parts.map((p, i) =>
                      i % 2 === 1 ? (
                        <mark
                          key={i}
                          className="rounded bg-ember-500/25 px-1 font-medium text-ember-200"
                        >
                          {p}
                        </mark>
                      ) : (
                        <span key={i}>{p}</span>
                      ),
                    )
                  : body}
              </p>
            )}
          </div>

          {note.type === "youtube" && ytThumb && (
            <div className="relative h-14 w-24 shrink-0 overflow-hidden rounded-lg border border-cyan-400/20 bg-gradient-to-br from-cyan-500/10 via-ink-900 to-ink-950 shadow-sm">
              <img
                src={ytThumb}
                alt=""
                className="h-full w-full object-cover transition-transform duration-[3s] ease-out group-hover:scale-[1.15]"
                onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
              />
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/20">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-black/65 text-cyan-300 ring-1 ring-cyan-400/40 backdrop-blur-xs">
                  <svg className="ml-0.5 h-2.5 w-2.5" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M2.5 1.8l7.5 4.2-7.5 4.2V1.8z" />
                  </svg>
                </span>
              </div>
              {ytDuration && (
                <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 py-0.2 font-mono text-[9px] font-medium text-white">
                  {fmtDuration(ytDuration)}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Inline Action Items Checklist */}
        {note.action_items.length > 0 && (
          <div className="mt-3 rounded-xl border border-ink-800/80 bg-ink-900/90 p-2.5 relative overflow-hidden">
            <div className="space-y-1.5">
              {note.action_items.slice(0, 2).map((it) => (
                <div
                  key={it.id}
                  onClick={(e) => {
                    if (!onToggleTask) return;
                    e.stopPropagation();
                    onToggleTask(note, it.id);
                  }}
                  className="flex items-start gap-2 text-xs transition-colors hover:text-ink-100"
                >
                  <span
                    className={`mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border transition-colors ${
                      it.done
                        ? "border-emerald-500/40 bg-emerald-500/20 text-emerald-300"
                        : "border-ink-500 bg-ink-900 hover:border-ember-400"
                    }`}
                  >
                    {it.done && <CheckIcon className="h-2.5 w-2.5" />}
                  </span>
                  <span
                    className={`line-clamp-1 leading-snug ${
                      it.done ? "text-ink-400 line-through" : "text-ink-200"
                    }`}
                  >
                    {it.text}
                  </span>
                </div>
              ))}
              {note.action_items.length > 2 && (
                <p className="pl-5 font-mono text-[10px] text-ink-400">
                  +{note.action_items.length - 2} more · {doneTasks.length}/{note.action_items.length} completed
                </p>
              )}
            </div>
            {/* Micro progress bar */}
            <div className="absolute bottom-0 left-0 h-[2px] w-full bg-white/[0.02]">
              <div 
                className="h-full bg-emerald-500/60 transition-all duration-500" 
                style={{ width: `${(doneTasks.length / note.action_items.length) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Footer Tags + Task Counter */}
      {(note.tags.length > 0 || openTasks.length > 0) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-white/[0.04] pt-2.5">
          {note.tags.slice(0, 5).map((t) => (
            <button
              key={t}
              type="button"
              onClick={(e) => {
                if (!onTagClick) return;
                e.stopPropagation();
                onTagClick(t);
              }}
              className="rounded-md border border-white/[0.06] bg-white/[0.03] px-2 py-0.5 font-mono text-[10.5px] text-ink-300 transition-all duration-200 hover:scale-105 hover:border-ember-400/40 hover:bg-ember-500/10 hover:text-ember-200"
              style={{ borderLeftColor: meta.accent, borderLeftWidth: '2px' }}
            >
              #{t}
            </button>
          ))}
          {note.tags.length > 5 && (
            <span className="font-mono text-[10px] text-ink-500">+{note.tags.length - 5}</span>
          )}
          {openTasks.length > 0 && (
            <span className="ml-auto rounded-full border border-ember-400/25 bg-ember-500/12 px-2 py-0.5 font-mono text-[10px] font-medium text-ember-300">
              {openTasks.length} open {openTasks.length === 1 ? "task" : "tasks"}
            </span>
          )}
        </div>
      )}
    </article>
  );
}
