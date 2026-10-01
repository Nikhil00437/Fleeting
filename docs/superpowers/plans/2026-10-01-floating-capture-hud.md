# Global Floating Capture HUD & Handy Dictation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight, system-wide floating dictation and quick-capture HUD for Fleeting, bringing Handy's 9-bar reactive audio visualizer, `Ctrl+Alt+Space` shortcut, and cursor auto-typing via `wtype` to Linux/Hyprland.

**Architecture:** Electron maintains a secondary frameless, transparent, always-on-top `hudWindow` loaded with `?mode=hud`. A dedicated React component (`CaptureHud.tsx`) connects to a custom Web Audio API hook (`useAudioVisualizer.ts`) to drive the 9-bar reactive waveform. When dictation completes, text is typed into the focused application via `/usr/bin/wtype` (if in Dictate mode) and ingested into Fleeting's backend for Whisper transcription and local LLM enrichment.

**Tech Stack:** Electron 34, React 19, TypeScript, Web Audio API (`AnalyserNode`), Tailwind CSS, `/usr/bin/wtype` (Wayland).

**Spec:** [`docs/superpowers/specs/2026-10-01-floating-capture-hud-design.md`](file:///home/nikhil/Projects/fleeting/docs/superpowers/specs/2026-10-01-floating-capture-hud-design.md)

## Global Constraints
- Target platform: Linux (Wayland / Hyprland), X11 compatible fallback.
- Primary shortcut: `Ctrl+Alt+Space` (`CommandOrControl+Alt+Space` in Electron).
- CLI toggle: `fleeting-app --hud`.
- Audio analyser: 9 smoothed frequency bars throttled to ~30 FPS (33ms).
- Fallback for `wtype`: clipboard copy via `wl-copy` if `wtype` fails.

---

### Task 1: Web Audio Analyser Hook (`useAudioVisualizer.ts`)

**Files:**
- Create: `frontend/src/hooks/useAudioVisualizer.ts`
- Test: `frontend/src/hooks/__tests__/useAudioVisualizer.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export interface AudioVisualizerState {
    isRecording: boolean;
    levels: number[];       // 9 normalized values (0..1)
    elapsed: number;      // Seconds
    error: string | null;
    start: () => Promise<void>;
    stop: () => Promise<Blob | null>;
    cancel: () => void;
  }
  ```

- [ ] **Step 1: Write test for audio visualizer level smoothing**
Create `frontend/src/hooks/__tests__/useAudioVisualizer.test.ts` testing exponential smoothing and level normalization:
```ts
import { describe, expect, it } from "vitest";

function smoothLevels(prev: number[], target: number[]): number[] {
  return prev.map((p, i) => p * 0.7 + (target[i] || 0) * 0.3);
}

describe("audio visualizer smoothing", () => {
  it("smooths incoming audio frequency buckets", () => {
    const prev = [0, 0, 0];
    const target = [1, 0.5, 0.2];
    const result = smoothLevels(prev, target);
    expect(result[0]).toBeCloseTo(0.3);
    expect(result[1]).toBeCloseTo(0.15);
    expect(result[2]).toBeCloseTo(0.06);
  });
});
```

- [ ] **Step 2: Run test to verify testing setup**
Run: `npm test` or verify with TypeScript.

- [ ] **Step 3: Implement `useAudioVisualizer.ts`**
Create `frontend/src/hooks/useAudioVisualizer.ts`:
```ts
import { useCallback, useEffect, useRef, useState } from "react";

const WAVE_BARS = 9;

export function useAudioVisualizer() {
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

  const cleanup = useCallback(() => {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    if (timerRef.current) clearInterval(timerRef.current);
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(() => {});
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((t) => t.stop());
    }
    animFrameRef.current = null;
    timerRef.current = null;
    mediaStreamRef.current = null;
    audioContextRef.current = null;
    analyserRef.current = null;
    setLevels(Array(WAVE_BARS).fill(0));
    smoothedRef.current = Array(WAVE_BARS).fill(0);
  }, []);

  const start = useCallback(async () => {
    cleanup();
    setError(null);
    setElapsed(0);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      mediaStreamRef.current = stream;

      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioCtx();
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.4;
      source.connect(analyser);
      analyserRef.current = analyser;

      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
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
          const smoothed = smoothedRef.current.map((prev, i) => prev * 0.7 + raw[i] * 0.3);
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
  }, [cleanup]);

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
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        cleanup();
        setIsRecording(false);
        resolve(blob);
      };
      recorder.stop();
    });
  }, [cleanup]);

  const cancel = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    cleanup();
    setIsRecording(false);
    chunksRef.current = [];
  }, [cleanup]);

  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  return { isRecording, levels, elapsed, error, start, stop, cancel };
}
```

- [ ] **Step 4: Commit**
```bash
git add frontend/src/hooks/useAudioVisualizer.ts
git commit -m "feat(audio): add reactive 9-bar audio visualizer hook with Web Audio API"
```

---

### Task 2: Handy-Inspired `CaptureHud.tsx` Component & Styles

**Files:**
- Create: `frontend/src/components/CaptureHud.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Produces:
  ```tsx
  export default function CaptureHud(): React.JSX.Element
  ```

- [ ] **Step 1: Add Handy overlay styles to `frontend/src/index.css`**
Add `.hud-pill`, `.swave`, `.sdot`, `.sspinner` styles:
```css
/* Handy Floating Dictation HUD Overlay */
.hud-pill {
  height: 52px;
  background: #23382e;
  border: 1px solid #3c5446;
  border-radius: 9999px;
  box-shadow: 0 16px 40px rgb(0 0 0 / 0.4), inset 0 1px 0 rgb(255 255 255 / 0.1);
  backdrop-filter: blur(16px);
  color: #f4f0e7;
}

.swave {
  display: flex;
  align-items: center;
  gap: 3px;
  height: 20px;
}
.swave i {
  display: block;
  width: 3px;
  min-height: 3px;
  border-radius: 9999px;
  background: #d8784c;
  transition: height 60ms ease;
}

.sdot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  background: #ef4444;
  box-shadow: 0 0 10px #ef4444;
  animation: pulse-ring 1.4s infinite;
}

.sspinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgb(255 255 255 / 0.2);
  border-top-color: #d8784c;
  border-radius: 9999px;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
```

- [ ] **Step 2: Implement `CaptureHud.tsx`**
Create `frontend/src/components/CaptureHud.tsx` supporting:
- Auto-recording on mount/show
- 9-bar reactive waveform
- Elapsed timer (`0:04`)
- Dictate mode vs Note mode toggle (`Tab`)
- Typing to active app via `desktop.typeText`
- Fleeting note submission via `api.captureAudio`
- Keyboard shortcuts: `Enter` to commit, `Esc` to cancel, `Tab` to toggle mode

- [ ] **Step 3: Run `npm run build` to verify compilation**
Run: `npm run build` in `frontend/`.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/components/CaptureHud.tsx frontend/src/index.css
git commit -m "feat(hud): implement Handy-style floating capture overlay component"
```

---

### Task 3: Electron Secondary `hudWindow`, Global Shortcut & `wtype` Integration

**Files:**
- Modify: `electron/main.cjs`
- Modify: `electron/preload.cjs`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Preload API extensions in `window.fleetingDesktop`:
  ```ts
  hideHud: () => Promise<void>;
  resizeHud: (height: number) => Promise<void>;
  typeText: (text: string) => Promise<boolean>;
  onHudTrigger: (cb: () => void) => () => void;
  ```

- [ ] **Step 1: Update `electron/preload.cjs`**
Expose HUD lifecycle and text-typing IPC handlers:
```js
hideHud: () => ipcRenderer.invoke("hud:hide"),
resizeHud: (height) => ipcRenderer.invoke("hud:resize", height),
typeText: (text) => ipcRenderer.invoke("hud:type-text", text),
onHudTrigger: (cb) => {
  const handler = () => cb();
  ipcRenderer.on("hud:trigger", handler);
  return () => ipcRenderer.removeListener("hud:trigger", handler);
}
```

- [ ] **Step 2: Update `electron/main.cjs`**
Implement:
1. `createHudWindow()`: 520x72 frameless floating window.
2. `globalShortcut.register("CommandOrControl+Alt+Space", toggleHud)`.
3. Second-instance check: `argv.includes("--hud")` triggers `toggleHud()`.
4. `hud:type-text`:
   - Hide `hudWindow` immediately so the previous application regains focus.
   - Run `spawn("wtype", ["--", text])` on Wayland.
   - If `wtype` is not present, fall back to copying text to clipboard and alerting user.

- [ ] **Step 3: Update `frontend/src/App.tsx` to mount `CaptureHud` when `?mode=hud`**
Check URL query `new URLSearchParams(window.location.search).get("mode") === "hud"`:
```tsx
const isHudMode = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("mode") === "hud";
if (isHudMode) {
  return <CaptureHud />;
}
```

- [ ] **Step 4: Verify full build**
Run: `npm run build` in `frontend/`.

- [ ] **Step 5: Commit**
```bash
git add electron/main.cjs electron/preload.cjs frontend/src/App.tsx
git commit -m "feat(desktop): wire up floating hudWindow, Ctrl+Alt+Space shortcut, and wtype auto-typing"
```

---

### Task 4: End-to-End Hyprland & Wayland Verification

**Files:**
- Modify: `bin/fleeting-app`
- Test: manual integration test with `wtype`

- [ ] **Step 1: Ensure `bin/fleeting-app` forwards `--hud` properly**
Verify that executing `fleeting-app --hud` launches or toggles the HUD window.

- [ ] **Step 2: Verify `wtype` emission into terminal**
Open a terminal, trigger HUD via `Ctrl+Alt+Space` or `fleeting-app --hud`, dictate a sentence, and confirm it is typed cleanly into the terminal.

- [ ] **Step 3: Commit and mark plan completed**
```bash
git add bin/fleeting-app
git commit -m "feat(hud): finalize CLI invocation and Wayland integration"
```
