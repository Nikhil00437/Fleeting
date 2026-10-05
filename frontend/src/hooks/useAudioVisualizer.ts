import { audioConstraints } from "../mic";
import { useCallback, useEffect, useRef, useState } from "react";

export const WAVE_BARS = 9;

export interface AudioVisualizerState {
  isRecording: boolean;
  levels: number[];       // 9 normalized values (0..1)
  elapsed: number;        // Seconds
  error: string | null;
  start: () => Promise<void>;
  stop: () => Promise<Blob | null>;
  cancel: () => void;
  /** #8: blob of everything recorded so far — valid WebM since it starts at byte 0. */
  snapshot: () => Blob | null;
}

export function smoothLevels(prev: number[], target: number[], smoothing = 0.7): number[] {
  return prev.map((p, i) => p * smoothing + (target[i] || 0) * (1 - smoothing));
}

export function useAudioVisualizer(): AudioVisualizerState {
  const [isRecording, setIsRecording] = useState(false);
  const [levels, setLevels] = useState<number[]>(Array(WAVE_BARS).fill(0));
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const smoothedRef = useRef<number[]>(Array(WAVE_BARS).fill(0));
  const timerRef = useRef<number | null>(null);
  const isStartingRef = useRef(false);

  const cleanup = useCallback(() => {
    if (animFrameRef.current !== null) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
    mediaRecorderRef.current = null;
    analyserRef.current = null;
    setLevels(Array(WAVE_BARS).fill(0));
    smoothedRef.current = Array(WAVE_BARS).fill(0);
  }, []);

  const start = useCallback(async () => {
    if (isStartingRef.current || isRecording) {
      return;
    }
    isStartingRef.current = true;
    try {
      cleanup();
      setError(null);
      setElapsed(0);
      chunksRef.current = [];

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: audioConstraints(),
        });
        mediaStreamRef.current = stream;

        const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioCtx) {
          throw new Error("Web Audio API not supported in this browser");
        }
        const ctx = new AudioCtx();
        if (ctx.state === "suspended") {
          await ctx.resume();
        }
        audioContextRef.current = ctx;

        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 64;
        analyser.smoothingTimeConstant = 0.4;
        source.connect(analyser);
        analyserRef.current = analyser;

        let options: MediaRecorderOptions | undefined = undefined;
        if (typeof MediaRecorder !== "undefined" && typeof MediaRecorder.isTypeSupported === "function") {
          if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
            options = { mimeType: "audio/webm;codecs=opus" };
          } else if (MediaRecorder.isTypeSupported("audio/webm")) {
            options = { mimeType: "audio/webm" };
          }
        }

        const recorder = options ? new MediaRecorder(stream, options) : new MediaRecorder(stream);
        recorder.ondataavailable = (e) => {
          if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
        };
        recorder.start(100);
        mediaRecorderRef.current = recorder;

        setIsRecording(true);

        timerRef.current = window.setInterval(() => {
          setElapsed((e) => e + 1);
        }, 1000);

        const buffer = new Uint8Array(analyser.frequencyBinCount);
        let lastTick = performance.now();

        const loop = (now: number) => {
          if (now - lastTick >= 33) {
            lastTick = now;
            analyser.getByteFrequencyData(buffer);
            const raw = Array.from({ length: WAVE_BARS }, (_, i) => {
              const idx = Math.min(i + 1, buffer.length - 1);
              return (buffer[idx] || 0) / 255;
            });
            const smoothed = smoothLevels(smoothedRef.current, raw);
            smoothedRef.current = smoothed;
            setLevels([...smoothed]);
          }
          animFrameRef.current = requestAnimationFrame(loop);
        };
        animFrameRef.current = requestAnimationFrame(loop);
      } catch (err) {
        cleanup();
        setIsRecording(false);
        setError(err instanceof Error ? err.message : "Microphone access denied");
      }
    } finally {
      isStartingRef.current = false;
    }
  }, [cleanup, isRecording]);

  const stop = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        cleanup();
        setIsRecording(false);
        resolve(null);
        return;
      }
      recorder.onstop = () => {
        const mimeType = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: mimeType });
        cleanup();
        setIsRecording(false);
        resolve(blob);
      };
      recorder.stop();
    });
  }, [cleanup]);

  const snapshot = useCallback((): Blob | null => {
    if (!chunksRef.current.length) return null;
    const recorder = mediaRecorderRef.current;
    return new Blob(chunksRef.current, { type: recorder?.mimeType || "audio/webm" });
  }, []);

  const cancel = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    cleanup();
    setIsRecording(false);
    chunksRef.current = [];
  }, [cleanup]);

  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  return { isRecording, levels, elapsed, error, start, stop, cancel, snapshot };
}
