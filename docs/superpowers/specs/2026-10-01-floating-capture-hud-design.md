# Design Spec: Global Floating Capture HUD & Handy Dictation Engine

## 1. Overview
The Global Floating Capture HUD brings an instant, system-wide speech-to-text dictation and thought capture interface to Fleeting on Linux/Wayland (Hyprland). Inspired by the open-source [Handy](https://github.com/cjpais/Handy) desktop application, it allows users to hit a global shortcut from any workspace or application, speak naturally, and either:
1. **Dictate directly into their active app** (typed at the cursor via `wtype`), and/or
2. **Capture into Fleeting's structured memory vault** (transcribed with Whisper and enriched into notes, action items, and tags via local LLM).

---

## 2. Architecture & Window Lifecycle

### 2.1 Multi-Window Setup in Electron (`electron/main.cjs`)
Electron manages two decoupled browser windows:
1. **`mainWindow`**: The primary full-screen desktop studio workbench (Inbox, Timeline, Tasks, Search, Settings).
2. **`hudWindow`**: A lightweight, frameless floating HUD window dedicated to dictation and quick capture.

### 2.2 `hudWindow` Specifications
- **Dimensions**: `width: 520px, height: 72px` (dynamically resizes to `height: 160px` when expanding to preview transcribed text).
- **Configuration**:
  ```js
  {
    width: 520,
    height: 72,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    title: 'Fleeting Dictation HUD',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  }
  ```
- **Positioning**: Center-aligned horizontally, anchored at `18%` screen height from the top of the active display.
- **Hyprland Compatibility**: Window title `Fleeting Dictation HUD` allows native floating window rules:
  ```ini
  windowrulev2 = float, title:^(Fleeting Dictation HUD)$
  windowrulev2 = pin, title:^(Fleeting Dictation HUD)$
  windowrulev2 = noborder, title:^(Fleeting Dictation HUD)$
  windowrulev2 = stayfocused, title:^(Fleeting Dictation HUD)$
  ```

### 2.3 Invocation & Triggers
- **Primary Global Shortcut**: `Ctrl+Alt+Space` (registered via `electron.globalShortcut`).
- **Compositor CLI Flag**: `fleeting-app --hud` (relayed via `app.requestSingleInstanceLock` / `second-instance`).
- **Toggle Semantics**:
  - If HUD is hidden: show window, acquire focus, arm microphone, start recording.
  - If HUD is recording: `Ctrl+Alt+Space` or `Enter` stops recording, transitions to processing, and submits audio.
  - `Escape` or window blur: cancels capture, releases media stream, and hides window.

---

## 3. Handy-Inspired Overlay UI & Audio Processing

### 3.1 Audio Analysis (Web Audio API)
- Connects `navigator.mediaDevices.getUserMedia({ audio: true })` to an `AudioContext` and `AnalyserNode` (`fftSize = 64`).
- Computes real-time frequency data throttled to ~30 FPS (every 33ms) with exponential smoothing (`prev * 0.7 + target * 0.3`).
- Maps 9 frequency bands to Handy's signature 9-bar reactive audio waveform (`.swave i`).

### 3.2 State Machine
The HUD transitions through four states:
1. **`arming`**: Requesting microphone access, initial buffer setup.
2. **`listening`**:
   - Left: Pulsing red/coral live recording dot.
   - Center: 9-bar dynamic audio visualizer reacting to vocal intensity.
   - Right: Elapsed timer (`0:04`), mode pill (`[Dictate]` vs `[Note]`), and stop/cancel controls.
3. **`processing`**:
   - Smooth transform into an animated spinner with status label (`"Transcribing with Whisper…"`).
4. **`preview` (Committed)**:
   - Expands to display transcribed text preview with a checkmark before auto-fading out after 1.2s.

---

## 4. Dual Output Engine (Dictation Typing + Knowledge Capture)

### 4.1 Mode Selection
Users toggle capture mode with `Tab` or by clicking the badge in the HUD:
- **Dictate Mode (Default)**:
  1. Stops recording.
  2. Submits audio to `/api/capture/audio`.
  3. Receives Whisper transcription string.
  4. Hides `hudWindow` (returning focus to the previously active window).
  5. Spawns `/usr/bin/wtype` (or copies to Wayland clipboard via `wl-copy` and emits paste) to type text directly into the user's active editor, shell, or browser.
  6. Simultaneously queues background note enrichment in Fleeting.
- **Note Mode**:
  1. Sends audio to `/api/capture/audio` solely for Fleeting knowledge ingestion without typing into the active application.

### 4.2 Error Handling & Fallbacks
- If `/usr/bin/wtype` fails or character encoding encounters special glyphs, fall back to `wl-copy` + `wl-paste` shortcut simulation.
- If microphone permission is denied, render an inline notice with a settings shortcut.
- If the backend is temporarily unreachable, buffer recorded audio locally in IndexedDB/sessionStorage for retry.

---

## 5. Security & Isolation
- `hudWindow` runs with `contextIsolation: true` and `nodeIntegration: false`.
- IPC methods exposed through `preload.cjs`:
  - `desktop.hideHud()`
  - `desktop.typeText(text: string)`
  - `desktop.onHudTrigger(callback)`
  - `desktop.setHudHeight(height: number)`

---

## 6. Testing & Verification Plan
1. **Unit & Component Testing**:
   - Verify Audio Analyser FFT calculations and smoothing algorithms.
   - Test HUD state machine transitions (`arming` → `listening` → `processing` → `preview` → `hidden`).
2. **Integration Testing**:
   - Test global shortcut `Ctrl+Alt+Space` on Hyprland.
   - Test CLI invocation `fleeting-app --hud` via second-instance event.
   - Test `wtype` text emission into a focused Kitty terminal and text editor.
   - Verify that completed captures appear in Fleeting's SQLite database and broadcast via SSE to the main studio window.
