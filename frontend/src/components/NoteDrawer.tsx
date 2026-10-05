import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import { fmtDuration, relTime, timeOfDay } from "../time";
import {
  ArchiveIcon,
  BotIcon,
  CheckIcon,
  CopyIcon,
  ExportIcon,
  LinkIcon,
  MicIcon,
  PinIcon,
  RefreshIcon,
  ShieldIcon,
  SparkIcon,
  StarIcon,
  TextIcon,
  TrashIcon,
  XIcon,
} from "./Icons";
import { StatusBadge } from "./NoteCard";
import { pipelineSteps, totalSecs } from "./pipeline";
import AudioPlayer from "./AudioPlayer";
import { runNoteAction } from "./actionRunner";
import { errorMessage } from "./settingsState";
import { NOTE_COLORS, colorHex } from "./noteColors";
import { diffStats, diffText } from "./textDiff";
import type { Note } from "../types";

interface NoteVersion {
  id: number;
  title: string;
  summary: string;
  raw_text: string;
  origin: string;
  created_at: string;
}

interface Props {
  note: Note;
  onClose: () => void;
  onUpdate: (note: Note) => void;
  onDelete?: (id: string) => void;
  onToast: (message: string, kind?: "ok" | "err") => void;
}

const TYPE_LABEL: Record<string, { icon: React.ReactNode; label: string; badgeCls: string }> = {
  text: {
    icon: <TextIcon className="h-3.5 w-3.5" />,
    label: "Note",
    badgeCls: "bg-ember-500/15 text-ember-300 ring-1 ring-ember-400/30",
  },
  voice: {
    icon: <MicIcon className="h-3.5 w-3.5" />,
    label: "Voice Memo",
    badgeCls: "bg-iris-500/15 text-iris-300 ring-1 ring-iris-400/30",
  },
  youtube: {
    icon: <LinkIcon className="h-3.5 w-3.5" />,
    label: "YouTube",
    badgeCls: "bg-cyan-500/15 text-cyan-300 ring-1 ring-cyan-400/30",
  },
};

function toMarkdown(n: Note): string {
  const lines = [`# ${n.title || "Untitled capture"}`];
  if (n.summary) lines.push("", n.summary);
  if (n.action_items.length) {
    lines.push("", "## Action items");
    n.action_items.forEach((it) => lines.push(`- [${it.done ? "x" : " "}] ${it.text}`));
  }
  if (n.raw_text) lines.push("", "## Content", "", n.raw_text);
  if (n.source?.url) lines.push("", `> ${n.source.url}`);
  return lines.join("\n");
}

function PipelineStepper({ note }: { note: Note }) {
  const steps = pipelineSteps(note);
  const interesting = note.status !== "done" || (note.source?.timings && Object.keys(note.source.timings).length > 0);
  if (!interesting) return null;
  return (
    <div className="mt-3 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
      <div className="flex items-center gap-1.5">
        {steps.map((s, i) => (
          <Fragment key={s.key}>
            {i > 0 && <span className="h-px w-3 bg-ink-700" />}
            <span
              className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium ${
                s.state === "done"
                  ? "text-emerald-300"
                  : s.state === "current"
                    ? "animate-pulse text-ember-300"
                    : s.state === "failed"
                      ? "text-red-300"
                      : "text-ink-500"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  s.state === "done" ? "bg-emerald-400" : s.state === "current" ? "bg-ember-400" : s.state === "failed" ? "bg-red-400" : "bg-ink-700"
                }`}
              />
              {s.label}
              {s.secs !== undefined && <span className="font-mono text-[9px] opacity-70">{s.secs}s</span>}
            </span>
          </Fragment>
        ))}
        {note.status === "done" && totalSecs(note) > 0 && (
          <span className="ml-auto font-mono text-[9.5px] text-ink-500">{totalSecs(note)}s total</span>
        )}
      </div>
    </div>
  );
}

export default function NoteDrawer({ note, onClose, onUpdate, onDelete, onToast }: Props) {
  const [title, setTitle] = useState(note.title);
  const [summary, setSummary] = useState(note.summary || "");
  const [tagInput, setTagInput] = useState("");
  const [newTaskText, setNewTaskText] = useState("");
  const [inspectorTab, setInspectorTab] = useState<
    "overview" | "raw" | "markdown" | "history"
  >("overview");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [snoozeOpen, setSnoozeOpen] = useState(false);
  const [regenOpen, setRegenOpen] = useState(false);
  const [regenModels, setRegenModels] = useState<string[] | null>(null);
  const [versions, setVersions] = useState<NoteVersion[] | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);

  useEffect(() => {
    setTitle(note.title);
    setSummary(note.summary || "");
    setConfirmDelete(false);
    setSnoozeOpen(false);
    setRegenOpen(false);
    setVersions(null);
    setVersionError(null);
    setNewTaskText("");
  }, [note.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setTitle(note.title);
    setSummary(note.summary || "");
  }, [note.title, note.summary]);

  async function patch(changes: Partial<Note>) {
    try {
      onUpdate(await api.updateNote(note.id, changes));
    } catch (e) {
      onToast(errorMessage(e), "err");
    }
  }

  // These two previously did `await api.<call>()` in an onClick with no catch:
  // a failed request was invisible, and on a failed delete onClose() never ran
  // so the drawer just sat there.
  async function reprocess() {
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.reprocess(note.id),
      success: "Reprocessing started",
      onDone: (updated) => onUpdate(updated),
    });
  }

  async function snooze(until: string | null) {
    setSnoozeOpen(false);
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.snoozeNote(note.id, until),
      success: until ? `Snoozed until ${until.replace("_", " ")}` : "Note woken up",
      onDone: (updated) => onUpdate(updated),
    });
  }

  function loadVersions() {
    setVersionError(null);
    api
      .noteVersions(note.id)
      .then(setVersions)
      .catch((e) => setVersionError(errorMessage(e)));
  }

  async function revertTo(versionId: number) {
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.revertVersion(note.id, versionId),
      success: "Reverted",
      onDone: (updated) => onUpdate(updated),
    });
  }

  async function regenerate(model?: string) {
    setRegenOpen(false);
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.regenerateNote(note.id, model),
      success: model ? `Regenerated with ${model}` : "Regenerated title, summary and tags",
      onDone: (updated) => onUpdate(updated),
    });
  }

  async function openRegenMenu() {
    setRegenOpen((v) => !v);
    if (!regenModels) {
      try {
        const probe = await api.testLLM();
        setRegenModels(probe.models ?? []);
      } catch {
        setRegenModels([]);
      }
    }
  }

  async function restoreFromTrash() {
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.restoreNote(note.id),
      success: "Note restored",
      onDone: (updated) => onUpdate(updated),
    });
  }

  async function remove() {
    setConfirmDelete(false);
    await runNoteAction({
      api,
      toast: onToast,
      action: () => api.deleteNote(note.id),
      success: "Note moved to trash",
      onDone: () => {
        onDelete?.(note.id);
        onClose();
      },
    });
  }

  async function toggleItem(itemId: string) {
    const items = note.action_items.map((it) =>
      it.id === itemId ? { ...it, done: !it.done } : it,
    );
    await patch({ action_items: items } as Partial<Note>);
  }

  async function addTaskItem() {
    const text = newTaskText.trim();
    if (!text) return;
    const nextItem = {
      id: `item-${Date.now().toString(36)}`,
      text,
      done: false,
    };
    setNewTaskText("");
    await patch({ action_items: [...note.action_items, nextItem] } as Partial<Note>);
  }

  async function removeTaskItem(itemId: string) {
    const items = note.action_items.filter((it) => it.id !== itemId);
    await patch({ action_items: items } as Partial<Note>);
  }

  async function addTag() {
    const t = tagInput
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9\u0900-\u097F-]/g, "");
    if (!t || note.tags.includes(t)) return setTagInput("");
    await patch({ tags: [...note.tags, t] } as Partial<Note>);
    setTagInput("");
  }

  const meta = note.source ?? {};
  const typeInfo = TYPE_LABEL[note.type] ?? TYPE_LABEL.text;
  const mdPreview = toMarkdown(note);

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  return (
    <aside className="note-page fixed bottom-6 left-0 right-0 top-14 z-40 flex flex-col bg-ink-950">
      {/* Docked Inspector Top Bar */}
      <div className="app-toolbar flex h-11 shrink-0 items-center gap-2 px-3.5">
        <span
          className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-[11px] font-medium ${typeInfo.badgeCls}`}
        >
          {typeInfo.icon}
          <span>{typeInfo.label}</span>
        </span>
        <span className="font-mono text-[10.5px] tabular-nums text-ink-400">
          {timeOfDay(note.created_at)} · {relTime(note.created_at)}
        </span>

        {/* Inspector Sub-Tabs */}
        <div className="ml-auto flex items-center rounded-lg border border-white/[0.06] bg-ink-950/90 p-0.5 text-[10.5px]">
          {(
            [
              { id: "overview", label: "Inspector" },
              { id: "raw", label: "Source" },
              { id: "markdown", label: "MD" },
              { id: "history", label: "History" },
            ] as const
          ).map((t) => (
            <button
              key={t.id}
              onClick={() => setInspectorTab(t.id)}
              className={`rounded-md px-2 py-0.5 transition-colors ${
                inspectorTab === t.id
                  ? "bg-white/[0.1] font-semibold text-ink-100"
                  : "text-ink-400 hover:text-ink-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-0.5 border-l border-white/[0.07] pl-1.5">
          <button
            onClick={() => void patch({ pinned: !note.pinned } as Partial<Note>)}
            className={`rounded-md p-1.5 transition-colors hover:bg-white/[0.06] ${
              note.pinned ? "text-ember-400" : "text-ink-400"
            }`}
            title={note.pinned ? "Unpin" : "Pin"}
          >
            <PinIcon filled={note.pinned} className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => void patch({ starred: !note.starred } as Partial<Note>)}
            className={`rounded-md p-1.5 transition-colors hover:bg-white/[0.06] ${
              note.starred ? "text-amber-300" : "text-ink-400"
            }`}
            title={note.starred ? "Unstar" : "Star"}
          >
            <StarIcon filled={note.starred} className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => void patch({ sensitive: !note.sensitive } as Partial<Note>)}
            className={`rounded-md p-1.5 transition-colors hover:bg-white/[0.06] ${
              note.sensitive ? "text-amber-300" : "text-ink-400"
            }`}
            title={
              note.sensitive
                ? "Sensitive — click to allow vault mirror & LLM again"
                : "Mark sensitive: excluded from vault mirror, LLM and assistant"
            }
          >
            <ShieldIcon className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={() => void patch({ archived: true } as Partial<Note>)}
            className="rounded-md p-1.5 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200"
            title="Archive"
          >
            <ArchiveIcon className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200"
            title="Close inspector (Esc)"
          >
            <XIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Scrollable Inspector Body */}
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {note.trashed_at && (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
            <span>
              In the trash — auto-purged after the retention window.
            </span>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={() => void restoreFromTrash()}
                className="rounded-lg border border-white/10 bg-white/10 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-white/20"
              >
                Restore
              </button>
              <button
                onClick={async () => {
                  try {
                    await api.purgeNote(note.id);
                    onDelete?.(note.id);
                    onClose();
                  } catch (e) {
                    onToast(errorMessage(e), "err");
                  }
                }}
                className="rounded-lg border border-red-400/30 bg-red-500/20 px-2.5 py-1 text-[11px] font-semibold text-red-200 hover:bg-red-500/30"
              >
                Delete forever
              </button>
            </div>
          </div>
        )}

        {/* Editable Note Title + Metadata Pills */}
        <div>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => title !== note.title && void patch({ title } as Partial<Note>)}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            placeholder="Untitled capture"
            className="w-full bg-transparent text-base font-bold tracking-tight text-ink-100 placeholder-ink-400 outline-none focus:text-ember-200"
          />

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <StatusBadge note={note} />
            {meta.enrichment && (
              <span className="inline-flex items-center gap-1 rounded-md border border-white/[0.06] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-ink-300">
                <BotIcon className="h-3 w-3 text-iris-400" />
                {meta.enrichment === "heuristic" ? "offline heuristics" : "local LLM"}
              </span>
            )}
            {Array.isArray(meta.transcription?.speakers) && meta.transcription.speakers.length > 0 && (
              <span className="rounded-md border border-white/[0.06] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-violet-300">
                {meta.transcription.speakers.length} speakers
              </span>
            )}
            {meta.transcription?.duration && (
              <span className="rounded-md border border-white/[0.06] bg-white/[0.03] px-2 py-0.5 font-mono text-[10px] text-iris-300">
                {fmtDuration(meta.transcription.duration)}
                {meta.transcription.language
                  ? ` · ${String(meta.transcription.language).toUpperCase()}`
                  : ""}
              </span>
            )}

            {/* #474: review lifecycle raw -> enriched -> reviewed -> final */}
            <select
              value={note.review_state ?? "enriched"}
              onChange={(e) => void patch({ review_state: e.target.value } as Partial<Note>)}
              className="rounded-md border border-white/[0.08] bg-ink-950 px-1.5 py-0.5 text-[10.5px] text-ink-200 outline-none"
              title="Review state — 'raw' means heuristic-only enrichment"
              aria-label="Review state"
            >
              <option value="raw">needs review</option>
              <option value="enriched">enriched</option>
              <option value="reviewed">reviewed</option>
              <option value="final">final</option>
            </select>
          </div>

          {/* #25: colour chips */}
          <div className="mt-2 flex items-center gap-1.5">
            {NOTE_COLORS.map((c) => (
              <button
                key={c.name}
                onClick={() => void patch({ color: note.color === c.name ? "" : c.name } as Partial<Note>)}
                className={`h-3.5 w-3.5 rounded-full transition-transform hover:scale-125 ${
                  note.color === c.name ? "ring-2 ring-white/70 ring-offset-1 ring-offset-ink-950" : ""
                }`}
                style={{ backgroundColor: c.hex }}
                title={`Colour: ${c.name}`}
                aria-label={`Set note colour ${c.name}`}
              />
            ))}
            {note.color && !colorHex(note.color) && (
              <button
                onClick={() => void patch({ color: "" } as Partial<Note>)}
                className="text-[10px] text-ink-400 underline"
              >
                clear unknown colour
              </button>
            )}
          </div>
        </div>

        <PipelineStepper note={note} />

        {note.audio_path && (
          <AudioPlayer noteId={note.id} words={note.source?.transcription?.words ?? []} />
        )}

        {note.status === "failed" && note.error && (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-200">
            <span className="min-w-0 flex-1">{note.error}</span>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={() => void reprocess()}
                className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/10 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-white/20"
              >
                <RefreshIcon className="h-3 w-3" /> Retry
              </button>
              <button
                onClick={() => void remove()}
                className="inline-flex items-center gap-1 rounded-lg border border-red-400/30 bg-red-500/20 px-2.5 py-1 text-[11px] font-semibold text-red-200 hover:bg-red-500/30"
              >
                <TrashIcon className="h-3 w-3" /> Delete
              </button>
            </div>
          </div>
        )}

        {inspectorTab === "overview" && (
          <>
            {/* YouTube metadata card */}
            {note.type === "youtube" && meta.url && (
              <a
                href={meta.url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => {
                  if (window.fleetingDesktop?.openExternal) {
                    e.preventDefault();
                    void window.fleetingDesktop.openExternal(meta.url);
                  }
                }}
                className="glass flex items-center gap-3 overflow-hidden rounded-xl p-2 transition-colors hover:border-cyan-400/40"
              >
                {meta.thumbnail && (
                  <img
                    src={meta.thumbnail}
                    alt=""
                    className="h-14 w-24 shrink-0 rounded-lg object-cover"
                    onError={(e) => ((e.target as HTMLImageElement).style.display = "none")}
                  />
                )}
                <div className="min-w-0 flex-1 pr-2">
                  <p className="truncate text-xs font-semibold text-ink-100">
                    {meta.title ?? "YouTube video"}
                  </p>
                  <p className="mt-0.5 text-[11px] text-cyan-300/90">
                    {meta.channel}
                    {meta.duration ? ` · ${fmtDuration(meta.duration)}` : ""}
                    {meta.method === "captions"
                      ? " · captions"
                      : meta.method === "whisper"
                        ? " · whisper"
                        : ""}
                  </p>
                </div>
              </a>
            )}

            {/* Editable AI Summary */}
            <div className="glass rounded-xl p-3.5">
              <p className="micro-label mb-1.5 !text-[9.5px] !text-ember-300">Executive Summary</p>
              <textarea
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                onBlur={() =>
                  summary !== (note.summary || "") && void patch({ summary } as Partial<Note>)
                }
                rows={3}
                placeholder="Add or edit summary…"
                className="w-full resize-none bg-transparent text-xs leading-relaxed text-ink-200 placeholder-ink-500 outline-none"
              />
            </div>

            {/* Interactive Action Items Checklist + Inline Creator */}
            <div className="glass rounded-xl p-3.5">
              <div className="mb-2 flex items-center justify-between">
                <p className="micro-label !text-[9.5px]">
                  Action Items ({note.action_items.filter((i) => i.done).length}/
                  {note.action_items.length})
                </p>
              </div>
              {note.action_items.length > 0 && (
                <ul className="mb-2.5 space-y-1.5">
                  {note.action_items.map((it) => (
                    <li
                      key={it.id}
                      className="group flex items-start gap-2.5 rounded-lg bg-ink-950/50 px-2.5 py-1.5 transition-colors hover:bg-ink-950"
                    >
                      <button
                        onClick={() => void toggleItem(it.id)}
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ${
                          it.done
                            ? "border-emerald-500/40 bg-emerald-500/20 text-emerald-300"
                            : "border-ink-500 bg-ink-900 hover:border-ember-400"
                        }`}
                      >
                        {it.done && <CheckIcon className="h-2.5 w-2.5" />}
                      </button>
                      <span
                        onClick={() => void toggleItem(it.id)}
                        className={`selectable flex-1 cursor-pointer text-xs leading-snug ${
                          it.done ? "text-ink-400 line-through" : "text-ink-100"
                        }`}
                      >
                        {it.text}
                      </span>
                      <button
                        onClick={() => void removeTaskItem(it.id)}
                        className="text-ink-500 opacity-0 transition-opacity group-hover:opacity-100 hover:text-red-300"
                        title="Remove task"
                      >
                        <XIcon className="h-3 w-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex items-center gap-1.5">
                <input
                  value={newTaskText}
                  onChange={(e) => setNewTaskText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void addTaskItem()}
                  placeholder="+ Add action item…"
                  className="h-7 flex-1 rounded-lg border border-dashed border-white/12 bg-ink-950/60 px-2.5 text-xs text-ink-200 placeholder-ink-500 outline-none focus:border-ember-500/50"
                />
                {newTaskText.trim() && (
                  <button
                    onClick={() => void addTaskItem()}
                    className="rounded-lg bg-ember-500/20 px-2.5 py-1 text-xs font-medium text-ember-300 hover:bg-ember-500/30"
                  >
                    Add
                  </button>
                )}
              </div>
            </div>

            {/* Tags Editor */}
            <div>
              <p className="micro-label mb-1.5 !text-[9.5px]">Tags</p>
              <div className="flex flex-wrap items-center gap-1.5">
                {note.tags.map((t) => (
                  <span
                    key={t}
                    className="group flex items-center gap-1 rounded-lg border border-white/[0.07] bg-white/[0.03] px-2.5 py-0.5 font-mono text-[11px] text-ink-200"
                  >
                    #{t}
                    <button
                      onClick={() =>
                        void patch({ tags: note.tags.filter((x) => x !== t) } as Partial<Note>)
                      }
                      className="text-ink-500 transition-colors hover:text-red-300"
                    >
                      <XIcon className="h-2.5 w-2.5" />
                    </button>
                  </span>
                ))}
                <input
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void addTag()}
                  onBlur={() => void addTag()}
                  placeholder="+ tag"
                  className="w-16 rounded-lg border border-dashed border-white/12 bg-transparent px-2 py-0.5 font-mono text-[11px] text-ink-200 placeholder-ink-500 outline-none transition-all focus:w-24 focus:border-ember-500/50"
                />
              </div>
            </div>

            {/* Raw Content / Transcript */}
            {note.raw_text && (
              <div>
                <p className="micro-label mb-1.5 !text-[9.5px]">
                  {note.type === "voice" || note.type === "youtube" ? "Transcript" : "Raw Content"}
                </p>
                <div className="selectable rounded-xl border border-white/[0.06] bg-ink-950/80 p-3.5 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-200">
                  {note.raw_text}
                </div>
              </div>
            )}
          </>
        )}

        {inspectorTab === "raw" && (
          <div>
            <p className="micro-label mb-1.5 !text-[9.5px]">Raw Source Text</p>
            <pre className="selectable overflow-x-auto rounded-xl border border-white/[0.06] bg-ink-950 p-3.5 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-200">
              {note.raw_text || "(empty)"}
            </pre>
          </div>
        )}

        {inspectorTab === "history" && (
          <HistoryPanel
            note={note}
            versions={versions}
            error={versionError}
            onVisible={loadVersions}
            onRevert={(id) => void revertTo(id)}
          />
        )}

        {inspectorTab === "markdown" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="micro-label !text-[9.5px]">Vault Markdown Preview</p>
              <button
                onClick={async () => {
                  await navigator.clipboard.writeText(mdPreview);
                  onToast("markdown copied");
                }}
                className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-0.5 text-[10.5px] text-ink-300 hover:text-ink-100"
              >
                <CopyIcon className="h-3 w-3" /> Copy MD
              </button>
            </div>
            <div
              className="md selectable rounded-xl border border-white/[0.06] bg-ink-950/80 p-3.5"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(mdPreview) }}
            />
          </div>
        )}
      </div>

      {/* Docked Inspector Footer Actions */}
      <div className="flex h-10 shrink-0 items-center gap-1 border-t border-white/[0.07] bg-ink-950/80 px-3">
        <div className="relative">
          <button
            onClick={() => setSnoozeOpen((v) => !v)}
            className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors hover:bg-white/[0.06] ${
              note.snoozed_until ? "text-iris-300" : "text-ink-300 hover:text-ink-100"
            }`}
            title="Hide this note until a chosen time"
          >
            zzz Snooze
          </button>
          {snoozeOpen && (
            <div className="glass-studio absolute bottom-9 left-0 z-50 w-44 rounded-xl p-1.5">
              {[
                { label: "Later today", value: "later" },
                { label: "Tomorrow", value: "tomorrow" },
                { label: "Next Monday", value: "next_monday" },
              ].map((p) => (
                <button
                  key={p.value}
                  onClick={() => void snooze(p.value)}
                  className="block w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-ink-200 hover:bg-white/[0.06]"
                >
                  {p.label}
                </button>
              ))}
              <label className="block w-full cursor-pointer rounded-lg px-2.5 py-1.5 text-[11px] text-ink-200 hover:bg-white/[0.06]">
                Pick a date…
                <input
                  type="date"
                  className="mt-1 w-full rounded-md border border-white/10 bg-ink-950 px-1.5 py-1 text-[11px] text-ink-100"
                  onChange={(e) => e.target.value && void snooze(e.target.value)}
                />
              </label>
              {note.snoozed_until && (
                <button
                  onClick={() => void snooze(null)}
                  className="block w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-iris-300 hover:bg-white/[0.06]"
                >
                  Wake now
                </button>
              )}
            </div>
          )}
        </div>
        <button
          onClick={() => void reprocess()}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:bg-white/[0.06] hover:text-ink-100"
          title="Re-run transcription + enrichment"
        >
          <RefreshIcon className="h-3 w-3" /> Reprocess
        </button>
        <div className="relative">
          <button
            onClick={() => void openRegenMenu()}
            className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:bg-white/[0.06] hover:text-ink-100"
            title="#20 Re-run title/summary/tags enrichment only"
          >
            <SparkIcon className="h-3 w-3" /> Regenerate
          </button>
          {regenOpen && (
            <div className="glass-studio absolute bottom-9 left-0 z-50 w-56 rounded-xl p-1.5">
              <button
                onClick={() => void regenerate()}
                className="block w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] text-ink-200 hover:bg-white/[0.06]"
              >
                Default model
              </button>
              {(regenModels ?? []).slice(0, 8).map((m) => (
                <button
                  key={m}
                  onClick={() => void regenerate(m)}
                  className="block w-full truncate rounded-lg px-2.5 py-1.5 text-left font-mono text-[10.5px] text-ink-300 hover:bg-white/[0.06]"
                >
                  {m}
                </button>
              ))}
              {regenModels !== null && regenModels.length === 0 && (
                <p className="px-2.5 py-1.5 text-[10.5px] text-ink-500">
                  No other models found on the server.
                </p>
              )}
            </div>
          )}
        </div>
        <button
          onClick={async () => {
            try {
              const r = await api.exportNote(note.id);
              onToast(`exported → ${r.path.replace(/^\/home\/[^/]+/, "~")}`);
            } catch (e) {
              onToast(errorMessage(e), "err");
            }
          }}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:bg-white/[0.06] hover:text-ink-100"
          title="Write to markdown vault"
        >
          <ExportIcon className="h-3 w-3" /> Export
        </button>
        <button
          onClick={() => {
            navigator.clipboard
              .writeText(toMarkdown(note))
              .then(() => onToast("markdown copied"))
              .catch((e: unknown) => onToast(errorMessage(e), "err"));
          }}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-300 transition-colors hover:bg-white/[0.06] hover:text-ink-100"
        >
          <CopyIcon className="h-3 w-3" /> Copy
        </button>
        <div className="ml-auto">
          {confirmDelete ? (
            <span className="flex items-center gap-1.5 text-[11px]">
              <span className="text-ink-400">Delete?</span>
              <button
                onClick={() => void remove()}
                className="rounded-md bg-red-500/20 px-2 py-0.5 font-semibold text-red-300 hover:bg-red-500/30"
              >
                Yes
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="rounded-md px-1.5 py-0.5 text-ink-400 hover:bg-white/[0.06]"
              >
                No
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-ink-400 transition-colors hover:bg-red-500/12 hover:text-red-300"
            >
              <TrashIcon className="h-3 w-3" /> Delete
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

/** #19/#21: version history with a raw-vs-clean diff against the current text. */
function HistoryPanel({
  note,
  versions,
  error,
  onVisible,
  onRevert,
}: {
  note: Note;
  versions: NoteVersion[] | null;
  error: string | null;
  onVisible: () => void;
  onRevert: (versionId: number) => void;
}) {
  useEffect(() => {
    if (versions === null) onVisible();
  }, [versions, onVisible]);

  if (error) {
    return <p className="text-xs text-red-300">{error}</p>;
  }
  if (versions === null) {
    return <div className="shimmer h-24 rounded-2xl" />;
  }
  if (versions.length === 0) {
    return (
      <div className="glass rounded-xl p-3.5 text-xs text-ink-400">
        No edits recorded yet — history appears when the note&apos;s content changes.
      </div>
    );
  }

  const original = versions.find((v) => (v.raw_text || "").trim()) ?? versions[0];
  const differs = (original.raw_text || "") !== (note.raw_text || "");
  const parts = differs ? diffText(original.raw_text || "", note.raw_text || "") : null;
  const stats = parts ? diffStats(parts) : null;

  return (
    <div className="space-y-3">
      <div className="glass rounded-xl p-3.5">
        <p className="micro-label mb-2 !text-[9.5px]">
          Original capture vs current text
        </p>
        {differs && parts ? (
          <>
            <p className="mb-2 font-mono text-[10px] text-ink-500">
              {stats && stats.added > 0 ? `+${stats.added} ` : ""}
              {stats && stats.removed > 0 ? `−${stats.removed}` : ""}
              {" words"}
            </p>
            <p className="selectable max-h-64 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed">
              {parts.map((p, i) =>
                p.type === "same" ? (
                  <span key={i} className="text-ink-400">
                    {p.text}
                  </span>
                ) : p.type === "add" ? (
                  <span key={i} className="rounded bg-emerald-500/15 text-emerald-300">
                    {p.text}
                  </span>
                ) : (
                  <span key={i} className="rounded bg-red-500/15 text-red-300 line-through">
                    {p.text}
                  </span>
                ),
              )}
            </p>
          </>
        ) : (
          <p className="text-xs text-ink-400">The text is unchanged since the capture.</p>
        )}
      </div>

      <div className="space-y-2">
        <p className="micro-label !text-[9.5px]">Snapshots ({versions.length})</p>
        {[...versions].reverse().map((v) => (
          <div key={v.id} className="glass flex items-center gap-2.5 rounded-xl px-3 py-2">
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs text-ink-200">
                {v.title || v.raw_text.slice(0, 60) || "(empty)"}
              </p>
              <p className="font-mono text-[10px] text-ink-500">
                {new Date(v.created_at).toLocaleString()} · {v.origin}
              </p>
            </div>
            <button
              onClick={() => onRevert(v.id)}
              className="shrink-0 rounded-lg border border-white/[0.08] bg-ink-900 px-2.5 py-1 text-[11px] text-ink-200 hover:border-ember-400/40 hover:text-ember-200"
              title="Restore title, summary and text from this snapshot"
            >
              Revert
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
