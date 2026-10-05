import { useEffect, useRef, useState } from "react";
import { audioConstraints } from "../mic";
import { api } from "../api";
import { LinkIcon, MicIcon, SendIcon, SparkIcon, StopIcon, TaskIcon, XIcon } from "./Icons";
import type { Note } from "../types";

interface Props {
  inputRef: React.RefObject<HTMLInputElement | null>;
  onCaptured: (note: Note) => void;
  onError: (message: string) => void;
  onCapturedTask?: (text: string) => void;
}

function pickMime(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

const YT_RE = /(youtube\.com\/(watch\?v=|shorts\/|embed\/|live\/)|youtu\.be\/)([\w-]{6,})/;
const TASK_RE = /\b(todo:|task:|remember to|need to|don't forget to)\b/i;

export default function CaptureBar({ inputRef, onCaptured, onError, onCapturedTask }: Props) {
  // #5: send this capture straight to Tasks instead of the Inbox
  const [destination, setDestination] = useState<"inbox" | "task">("inbox");
  const [repo, setRepo] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  // #79: drag audio/text/URL onto the bar to capture
  const [dragOver, setDragOver] = useState(false);
  // brief green confirm flash on the bar after a capture lands
  const [sent, setSent] = useState(false);

  function flashSent() {
    setSent(true);
    window.setTimeout(() => setSent(false), 1200);
  }

  // recording state
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const cancelledRef = useRef(false);
  const rafRef = useRef<number>(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      cancelAnimationFrame(rafRef.current);
      if (timerRef.current) window.clearInterval(timerRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // Stop the browser navigating away when a drop misses the bar
  useEffect(() => {
    const block = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", block);
    window.addEventListener("drop", block);
    return () => {
      window.removeEventListener("dragover", block);
      window.removeEventListener("drop", block);
    };
  }, []);

  async function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    const file = e.dataTransfer.files?.[0];
    if (file) {
      if (file.type.startsWith("audio/")) {
        setBusy(true);
        try {
          const note = await api.captureAudio(file, file.name || "drop.webm");
          onCaptured(note);
          flashSent();
        } catch (err) {
          onError(err instanceof Error ? err.message : String(err));
        } finally {
          setBusy(false);
        }
      } else if (file.size < 200_000) {
        await captureText(await file.text());
      } else {
        onError("dropped file is too large to read as text");
      }
      return;
    }
    const payload = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain")).trim();
    if (payload) await captureText(payload);
  }

  async function captureText(t: string) {
    const trimmed = t.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    try {
      if (destination === "task") {
        await api.createTask({ text: trimmed, repo: repo.trim() || undefined });
        onCapturedTask?.(trimmed);
        setText("");
        flashSent();
        return;
      }
      const yt = trimmed.match(YT_RE);
      const note = yt
        ? await api.captureYouTube(`https://youtu.be/${yt[3]}`)
        : await api.captureText(trimmed);
      onCaptured(note);
      setText("");
      flashSent();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints() });
      streamRef.current = stream;
      cancelledRef.current = false;

      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128) / 128);
        setLevel(peak);
        rafRef.current = requestAnimationFrame(tick);
      };
      rafRef.current = requestAnimationFrame(tick);

      const mimeType = pickMime();
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      rec.onstop = () => {
        ctx.close();
        if (cancelledRef.current) return;
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        void upload(blob);
      };
      rec.start(250);
      recorderRef.current = rec;
      setRecording(true);
      setElapsed(0);
      timerRef.current = window.setInterval(() => setElapsed((s) => s + 0.25), 250);
    } catch {
      onError("microphone unavailable — check browser permissions");
    }
  }

  function stopRecording(cancel = false) {
    cancelledRef.current = cancel;
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
    cancelAnimationFrame(rafRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  async function upload(blob: Blob) {
    if (blob.size < 1200) {
      onError("recording too short");
      return;
    }
    setBusy(true);
    try {
      const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
      const note = await api.captureAudio(blob, `memo.${ext}`);
      onCaptured(note);
      flashSent();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const isYT = YT_RE.test(text);
  const isTask = !isYT && TASK_RE.test(text);

  return (
    <div
      className={`flex w-full max-w-2xl flex-col gap-1 rounded-xl transition-shadow ${dragOver ? "ring-2 ring-ember-400/70" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => void handleDrop(e)}
    >
      <div className="flex w-full items-center gap-1.5">
      {recording ? (
        <div className="flex h-8 flex-1 items-center gap-2.5 rounded-xl border border-ember-500/45 bg-ink-950/95 px-3 shadow-[0_0_20px_rgb(245_158_11/0.12)]">
          <button
            onClick={() => stopRecording(false)}
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ember-500 text-ink-950 pulse-ring"
            title="Stop & transcribe"
          >
            <StopIcon className="h-2.5 w-2.5" />
          </button>
          <span className="rounded-md bg-ember-500/20 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold text-ember-300 uppercase">
            rec
          </span>
          <div className="flex h-4 flex-1 items-center gap-[2px]" aria-hidden>
            {Array.from({ length: 36 }).map((_, i) => {
              const wave =
                0.15 + level * Math.abs(Math.sin(i * 0.65 + elapsed * 6)) * (0.45 + level);
              return (
                <div
                  key={i}
                  className="w-[2.5px] rounded-full bg-gradient-to-t from-iris-400 to-ember-400"
                  style={{ height: `${Math.min(100, wave * 100)}%` }}
                />
              );
            })}
          </div>
          <span className="font-mono text-xs tabular-nums text-ember-300">
            {Math.floor(elapsed / 60)}:{String(Math.floor(elapsed % 60)).padStart(2, "0")}
          </span>
          <button
            onClick={() => stopRecording(true)}
            className="rounded p-1 text-ink-400 transition-colors hover:bg-ink-800 hover:text-red-300"
            title="Cancel recording"
          >
            <XIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : (
        <div className="relative flex-1">
          <div className="pointer-events-none absolute top-1/2 left-3 flex -translate-y-1/2 items-center">
            {isYT ? (
              <LinkIcon className="h-3.5 w-3.5 text-cyan-400" />
            ) : isTask ? (
              <TaskIcon className="h-3.5 w-3.5 text-emerald-400" />
            ) : (
              <SparkIcon className="h-3.5 w-3.5 text-ember-400" />
            )}
          </div>
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) void captureText(text);
            }}
            placeholder="Capture a thought, 'todo: …' task, or paste a YouTube URL…"
            spellCheck={false}
            className={`h-8 w-full rounded-xl border bg-ink-950/90 pr-24 pl-8.5 text-xs text-ink-100 placeholder-ink-400 shadow-[inset_0_1px_0_rgb(255_255_255/0.04)] outline-none transition-all focus:border-ember-500/50 focus:bg-ink-950 focus:shadow-[0_0_0_3px_rgb(245_158_11/0.1)] ${
              sent ? "border-emerald-400/70 ring-2 ring-emerald-400/20" : "border-ink-800"
            }`}
          />
          <div className="absolute top-1/2 right-1.5 flex -translate-y-1/2 items-center gap-1">
            {isYT && (
              <span className="rounded-md bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold text-cyan-300 ring-1 ring-cyan-400/30">
                YT
              </span>
            )}
            {isTask && (
              <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold text-emerald-300 ring-1 ring-emerald-400/30">
                Task
              </span>
            )}
            {text.trim() ? (
              <button
                onClick={() => void captureText(text)}
                disabled={busy}
                className="flex items-center gap-1 rounded-lg bg-gradient-to-br from-ember-400 to-ember-600 px-2.5 py-0.5 text-[11px] font-semibold text-ink-950 shadow-xs transition-all hover:brightness-110 disabled:opacity-50"
              >
                <SendIcon className="h-2.5 w-2.5" />
                <span>Capture</span>
              </button>
            ) : (
              <kbd className="hidden rounded-md border border-ink-800 bg-ink-900/90 px-1.5 py-0.5 font-mono text-[9.5px] text-ink-400 sm:inline">
                n
              </kbd>
            )}
          </div>
        </div>
      )}
      {!recording && (
        <button
          onClick={() => void startRecording()}
          disabled={busy}
          title="Record voice memo (local Whisper)"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-ink-800 bg-ink-950/90 text-ink-300 shadow-[inset_0_1px_0_rgb(255_255_255/0.04)] transition-all hover:border-iris-400/50 hover:bg-iris-500/10 hover:text-iris-300 disabled:opacity-50"
        >
          <MicIcon className="h-3.5 w-3.5" />
        </button>
      )}
      </div>
      <div className="flex items-center gap-2 px-1">
        <div className="flex overflow-hidden rounded-md border border-ink-800 text-[9.5px] font-semibold">
          {(["inbox", "task"] as const).map((d) => (
            <button
              key={d}
              onClick={() => setDestination(d)}
              className={`px-2 py-0.5 capitalize transition-colors ${destination === d ? "bg-ember-500/25 text-ember-300" : "text-ink-500 hover:text-ink-300"}`}
            >
              {d === "inbox" ? "Inbox" : "Task"}
            </button>
          ))}
        </div>
        {destination === "task" && (
          <input
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="repo (optional)"
            className="w-28 rounded-md border border-ink-800 bg-ink-950/90 px-2 py-0.5 text-[10px] text-ink-300 placeholder-ink-500 outline-none focus:border-ember-500/40"
          />
        )}
      </div>
    </div>
  );
}
