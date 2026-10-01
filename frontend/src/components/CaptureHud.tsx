import React, { useCallback, useEffect, useRef, useState } from "react";
import { useAudioVisualizer } from "../hooks/useAudioVisualizer";
import { api } from "../api";

export type CaptureHudState = "listening" | "processing" | "preview" | "error";
export type CaptureMode = "dictate" | "note";

export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function calculateBarHeight(level: number, minHeight = 3, maxHeight = 20): number {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0));
  return Math.round(minHeight + clamped * (maxHeight - minHeight));
}

export interface CaptureHudProps {
  onDone?: () => void;
  initialMode?: CaptureMode;
  initialState?: CaptureHudState;
}

export default function CaptureHud({
  onDone,
  initialMode = "dictate",
  initialState,
}: CaptureHudProps = {}): React.JSX.Element {
  const { levels, elapsed, error: audioError, start, stop, cancel } = useAudioVisualizer();

  const [state, setState] = useState<CaptureHudState>(
    () => initialState || (audioError ? "error" : "listening")
  );
  const [mode, setMode] = useState<CaptureMode>(initialMode);
  const [previewText, setPreviewText] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(() => audioError || null);

  const closeTimerRef = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const getDesktop = () => (typeof window !== "undefined" ? window.fleetingDesktop : undefined);

  const handleCancel = useCallback(() => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    cancel();
    const desktop = getDesktop();
    void desktop?.hideHud?.();
    void desktop?.resizeHud?.(72);
    onDone?.();
  }, [cancel, onDone]);

  const handleCommit = useCallback(async () => {
    if (stateRef.current !== "listening") return;
    setState("processing");

    try {
      const blob = await stop();
      if (!blob || blob.size === 0) {
        throw new Error("No audio recorded");
      }

      const note = await api.captureAudio(blob);
      const text = (note.raw_text || note.title || "").trim();
      setPreviewText(text);

      const desktop = getDesktop();
      if (modeRef.current === "dictate" && text) {
        if (desktop?.typeText) {
          await desktop.typeText(text);
        }
      }

      setState("preview");
      void desktop?.resizeHud?.(140);

      closeTimerRef.current = window.setTimeout(() => {
        const d = getDesktop();
        void d?.hideHud?.();
        void d?.resizeHud?.(72);
        onDone?.();
      }, 1200);
    } catch (err) {
      setState("error");
      setErrorMessage(err instanceof Error ? err.message : "Transcription failed");
      void getDesktop()?.resizeHud?.(72);
    }
  }, [stop, onDone]);

  const handleRestart = useCallback(async () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setPreviewText("");
    setErrorMessage(null);
    setState("listening");
    void getDesktop()?.resizeHud?.(72);

    try {
      await start();
    } catch (err) {
      setState("error");
      setErrorMessage(err instanceof Error ? err.message : "Failed to access microphone");
    }
  }, [start]);

  // Sync audio hook errors
  useEffect(() => {
    if (audioError) {
      setState("error");
      setErrorMessage(audioError);
    }
  }, [audioError]);

  // Initial mount auto-start & body background isolation
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.body.classList.add("hud-body");
    }
    void start().catch((err) => {
      setState("error");
      setErrorMessage(err instanceof Error ? err.message : "Microphone access denied");
    });

    return () => {
      if (typeof document !== "undefined") {
        document.body.classList.remove("hud-body");
      }
      if (closeTimerRef.current) {
        clearTimeout(closeTimerRef.current);
      }
    };
  }, [start]);

  // Keyboard shortcut handlers
  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (stateRef.current === "listening") {
          void handleCommit();
        } else if (stateRef.current === "error") {
          void handleRestart();
        }
      } else if (e.key === "Tab") {
        e.preventDefault();
        setMode((prev) => (prev === "dictate" ? "note" : "dictate"));
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleCommit, handleCancel, handleRestart]);

  // Listen to desktop global shortcut or second-instance trigger
  useEffect(() => {
    const desktop = getDesktop();
    if (!desktop?.onHudTrigger) return;
    const unsub = desktop.onHudTrigger(() => {
      if (stateRef.current === "listening") {
        void handleCommit();
      } else {
        void handleRestart();
      }
    });
    return unsub;
  }, [handleCommit, handleRestart]);

  return (
    <div
      id="capture-hud-root"
      className="w-full h-full min-h-screen flex items-center justify-center p-2 select-none"
    >
      <div className="w-full max-w-[500px]">
        {state === "listening" && (
          <div className="w-full h-[52px] hud-pill px-4 flex items-center justify-between gap-3 animate-in fade-in zoom-in-95 duration-150">
            {/* Left: Recording dot & 9-bar reactive wave */}
            <div className="flex items-center gap-3">
              <div className="sdot" title="Recording live" />
              <div
                className="swave"
                aria-label="Reactive audio wave"
                role="img"
              >
                {levels.map((lvl, i) => (
                  <i
                    key={i}
                    style={{ height: `${calculateBarHeight(lvl)}px` }}
                  />
                ))}
              </div>
            </div>

            {/* Center: Elapsed timer */}
            <div className="font-mono text-sm font-medium tracking-wider text-neutral-300">
              {formatElapsed(elapsed)}
            </div>

            {/* Right: Mode pill and commit/cancel controls */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setMode((m) => (m === "dictate" ? "note" : "dictate"))}
                title="Toggle mode (Tab)"
                className={`px-2.5 py-1 text-xs font-semibold rounded-full border transition-all flex items-center gap-1.5 cursor-pointer ${
                  mode === "dictate"
                    ? "bg-[#d8784c]/20 text-[#d8784c] border-[#d8784c]/40 hover:bg-[#d8784c]/30"
                    : "bg-[#4b786b]/20 text-[#668d7e] border-[#4b786b]/40 hover:bg-[#4b786b]/30"
                }`}
              >
                <span>{mode === "dictate" ? "Dictate" : "Note"}</span>
                <span className="text-[10px] opacity-60 font-mono">Tab</span>
              </button>

              <button
                type="button"
                onClick={() => void handleCommit()}
                title="Stop & transcribe (Enter)"
                className="w-7 h-7 rounded-full bg-[#d8784c] hover:bg-[#e08357] text-[#23382e] flex items-center justify-center transition-transform active:scale-95 shadow cursor-pointer"
              >
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </button>

              <button
                type="button"
                onClick={handleCancel}
                title="Cancel capture (Esc)"
                className="w-7 h-7 rounded-full hover:bg-white/10 text-neutral-400 hover:text-neutral-200 flex items-center justify-center transition-colors cursor-pointer"
              >
                <svg
                  className="w-4 h-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>
        )}

        {state === "processing" && (
          <div className="w-full h-[52px] hud-pill px-4 flex items-center justify-between gap-3 animate-in fade-in duration-150">
            <div className="flex items-center gap-3">
              <div className="sspinner" />
              <span className="text-xs text-neutral-200 font-medium">
                Transcribing with Whisper…
              </span>
            </div>
            <span className="text-[11px] px-2.5 py-0.5 rounded-full bg-white/10 text-neutral-300 border border-white/10 font-medium">
              {mode === "dictate" ? "Dictate" : "Note"}
            </span>
          </div>
        )}

        {state === "preview" && (
          <div className="w-full hud-card p-3.5 flex flex-col gap-2 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-semibold text-emerald-400">
                <svg
                  className="w-4 h-4"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <span>
                  {mode === "dictate" ? "Typed at cursor" : "Saved to Fleeting vault"}
                </span>
              </div>
              <span className="text-[10px] text-neutral-400 font-mono">Closing…</span>
            </div>
            {previewText ? (
              <p className="text-xs text-neutral-200 line-clamp-3 italic bg-black/25 p-2 rounded-lg border border-white/5 font-sans leading-relaxed">
                &ldquo;{previewText}&rdquo;
              </p>
            ) : (
              <p className="text-xs text-neutral-400 italic">Empty transcription</p>
            )}
          </div>
        )}

        {state === "error" && (
          <div className="w-full h-[52px] hud-pill px-4 flex items-center justify-between gap-3 border-red-500/50 animate-in fade-in duration-150">
            <div className="flex items-center gap-2 text-xs text-red-300 truncate max-w-[320px]">
              <svg
                className="w-4 h-4 text-red-400 shrink-0"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span className="truncate">{errorMessage || "Capture error"}</span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={() => void handleRestart()}
                className="px-2.5 py-1 text-xs rounded-full bg-white/10 hover:bg-white/20 text-neutral-200 cursor-pointer font-medium transition-colors"
              >
                Retry
              </button>
              <button
                type="button"
                onClick={handleCancel}
                title="Close"
                className="w-6 h-6 rounded-full hover:bg-white/10 text-neutral-400 hover:text-neutral-200 flex items-center justify-center cursor-pointer transition-colors"
              >
                ×
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
