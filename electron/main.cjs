const {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  Tray,
  nativeImage,
  session,
  shell,
  clipboard,
  globalShortcut,
  Notification,
  screen,
} = require("electron");
const { spawn, execFile } = require("child_process");
const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");

// Native Wayland / Hyprland support
app.commandLine.appendSwitch("ozone-platform-hint", "auto");
app.commandLine.appendSwitch("enable-features", "WaylandWindowDecorations");
app.setName("fleeting");
if (typeof app.setDesktopName === "function") {
  app.setDesktopName("fleeting.desktop");
}

const BACKEND_PORT = Number(process.env.FLEETING_PORT || 7425);
const BACKEND_URL = process.env.FLEETING_URL || `http://127.0.0.1:${BACKEND_PORT}`;
const ROOT_DIR = path.resolve(__dirname, "..");
const BACKEND_DIR = path.join(ROOT_DIR, "backend");
const ICON_PATH = path.join(ROOT_DIR, "deploy", "fleeting.png");
const TRAY_ICON_PATH = path.join(ROOT_DIR, "deploy", "fleeting-tray.png");
const STATE_FILE = path.join(os.homedir(), ".config", "fleeting", "window-state.json");
const CONFIG_FILE = path.join(os.homedir(), ".config", "fleeting", "config.toml");

/**
 * Tray-originated writes hit the same host guard as the UI, so they need the
 * bearer token when one is configured. Read once at startup — this file is
 * tiny and the tray must not block on it per click.
 */
function apiToken() {
  try {
    const text = fs.readFileSync(CONFIG_FILE, "utf8");
    const section = text.match(/\[activity\]([\s\S]*?)(\n\[|$)/);
    const token = section && section[1].match(/^\s*api_token\s*=\s*"([^"]*)"/m);
    return token ? token[1] : "";
  } catch {
    return "";
  }
}

let authToken = "";

function apiPost(pathname, body) {
  const headers = { "Content-Type": "application/json" };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  return fetch(`${BACKEND_URL}${pathname}`, {
    method: "POST",
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
}

let mainWindow = null;
let hudWindow = null;
let tray = null;
let backendProc = null;
let isQuitting = false;

function loadWindowState() {
  try {
    if (fs.existsSync(STATE_FILE)) {
      return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
    }
  } catch {
    /* ignore corrupt state */
  }
  return { width: 1360, height: 860, maximized: false };
}

function saveWindowState(win) {
  if (!win || win.isDestroyed()) return;
  try {
    const maximized = win.isMaximized();
    const bounds = maximized ? loadWindowState() : win.getBounds();
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    fs.writeFileSync(
      STATE_FILE,
      JSON.stringify({
        width: bounds.width || 1360,
        height: bounds.height || 860,
        x: bounds.x,
        y: bounds.y,
        maximized,
      }),
    );
  } catch {
    /* ignore write errors */
  }
}

function probeHealth() {
  return new Promise((resolve) => {
    const req = http.get(`${BACKEND_URL}/api/health`, { timeout: 1200 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

async function ensureBackend() {
  if (await probeHealth()) return true;

  // Spawn FastAPI backend via uv
  try {
    backendProc = spawn(
      "uv",
      [
        "run",
        "uvicorn",
        "fleeting.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        String(BACKEND_PORT),
      ],
      {
        cwd: BACKEND_DIR,
        stdio: "ignore",
        detached: false,
      },
    );
    backendProc.on("exit", () => {
      backendProc = null;
    });
  } catch {
    return false;
  }

  for (let i = 0; i < 60; i++) {
    if (await probeHealth()) return true;
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

const SPLASH_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<style>
  html, body {
    margin: 0; padding: 0; width: 100%; height: 100%;
    background: #090b10; color: #f3f5fa;
    font-family: system-ui, -apple-system, sans-serif;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    user-select: none; -webkit-app-region: drag;
  }
  .orb {
    width: 44px; height: 44px; border-radius: 12px;
    background: linear-gradient(135deg, #fbbf24, #d97706);
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 12px 32px rgba(245, 158, 11, 0.28);
    margin-bottom: 16px;
  }
  .title { font-size: 16px; font-weight: 700; letter-spacing: -0.02em; }
  .sub {
    margin-top: 6px; font-family: monospace; font-size: 11px; color: #7a88ab;
    display: flex; align-items: center; gap: 8px;
  }
  .dot {
    width: 7px; height: 7px; border-radius: 50%; background: #f59e0b;
    animation: pulse 1.2s infinite ease-in-out;
  }
  @keyframes pulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }
</style>
</head>
<body>
  <div class="orb">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#090b10" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
    </svg>
  </div>
  <div class="title">Fleeting</div>
  <div class="sub"><span class="dot"></span> starting local engine…</div>
</body>
</html>`;

async function createWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
    return mainWindow;
  }

  const state = loadWindowState();

  mainWindow = new BrowserWindow({
    width: state.width || 1360,
    height: state.height || 860,
    x: state.x,
    y: state.y,
    minWidth: 940,
    minHeight: 600,
    frame: false,
    autoHideMenuBar: true,
    backgroundColor: "#090b10",
    title: "Fleeting",
    show: !process.argv.includes("--hud"),
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });

  if (state.maximized && !process.argv.includes("--hud")) {
    mainWindow.maximize();
  }

  mainWindow.on("maximize", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("window:maximized", true);
      saveWindowState(mainWindow);
    }
  });
  mainWindow.on("unmaximize", () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("window:maximized", false);
      saveWindowState(mainWindow);
    }
  });
  mainWindow.on("resize", () => {
    if (mainWindow && !mainWindow.isDestroyed()) saveWindowState(mainWindow);
  });
  mainWindow.on("move", () => {
    if (mainWindow && !mainWindow.isDestroyed()) saveWindowState(mainWindow);
  });
  mainWindow.on("close", () => {
    if (mainWindow && !mainWindow.isDestroyed()) saveWindowState(mainWindow);
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  // Open external links in default system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("http://") || url.startsWith("https://")) {
      if (!url.startsWith(BACKEND_URL)) {
        shell.openExternal(url);
        return { action: "deny" };
      }
    }
    return { action: "allow" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(BACKEND_URL) && !url.startsWith("data:")) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  const up = await probeHealth();
  if (!up) {
    await mainWindow.loadURL(
      `data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`,
    );
    await ensureBackend();
  }
  await mainWindow.loadURL(BACKEND_URL);
  return mainWindow;
}

async function showMainWindow(navigateTarget) {
  if (!mainWindow || mainWindow.isDestroyed()) {
    await createWindow();
  } else {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  }
  if (navigateTarget && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("app:navigate", navigateTarget);
  }
}

async function createHudWindow() {
  if (hudWindow && !hudWindow.isDestroyed()) {
    return hudWindow;
  }

  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenWidth, height: screenHeight, x: screenX = 0, y: screenY = 0 } =
    primaryDisplay.workArea || primaryDisplay.bounds;

  const hudWidth = 520;
  const hudHeight = 72;
  const x = Math.round(screenX + (screenWidth - hudWidth) / 2);
  const y = Math.round(screenY + screenHeight * 0.18);

  hudWindow = new BrowserWindow({
    width: hudWidth,
    height: hudHeight,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    backgroundColor: "#00000000",
    hasShadow: false,
    title: "Fleeting Dictation HUD",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });

  hudWindow.setVisibleOnAllWorkspaces?.(true, { visibleOnFullScreen: true });
  hudWindow.setAlwaysOnTop(true, "pop-up-menu");

  hudWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      hudWindow.hide();
    }
  });

  await hudWindow.loadURL(`${BACKEND_URL}?mode=hud`);
  return hudWindow;
}

async function toggleHud() {
  if (!hudWindow || hudWindow.isDestroyed()) {
    await createHudWindow();
  }
  if (!hudWindow) return;

  if (hudWindow.isVisible()) {
    hudWindow.webContents.send("hud:trigger");
  } else {
    hudWindow.show();
    hudWindow.focus();
    hudWindow.webContents.send("hud:trigger");
  }
}

function fallbackCopy(text) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (!settled) {
        settled = true;
        resolve(result);
      }
    };

    let copiedToClipboard = false;
    try {
      clipboard.writeText(text);
      copiedToClipboard = true;
    } catch {
      /* ignore */
    }

    const wlCopyBin = fs.existsSync("/usr/bin/wl-copy") ? "/usr/bin/wl-copy" : "wl-copy";
    let copyProc;
    try {
      copyProc = spawn(wlCopyBin, ["--", text]);
    } catch {
      finish(copiedToClipboard);
      return;
    }

    copyProc.on("error", () => finish(copiedToClipboard));
    copyProc.on("exit", (code) => finish(code === 0 || copiedToClipboard));
  });
}

// #3: clipboard hotkey — primary selection if present, else clipboard,
// tagged with the active window's title so Inbox knows where it came from.
function runCmd(cmd, args) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 2000 }, (err, stdout) => resolve(err ? "" : String(stdout || "")));
  });
}

async function captureClipboard() {
  let text = (await runCmd("wl-paste", ["--primary", "--no-newline"])).trim();
  if (!text) text = (clipboard.readText() || "").trim();
  if (!text) {
    new Notification({ title: "Fleeting", body: "Nothing on the clipboard to capture" }).show();
    return;
  }
  let sourceTitle = null;
  try {
    const raw = await runCmd("hyprctl", ["activewindow", "-j"]);
    sourceTitle = JSON.parse(raw)?.title || null;
  } catch {
    /* hyprctl missing or window has no title — fine */
  }
  try {
    const resp = await apiPost("/api/capture/text", {
      text,
      source_title: sourceTitle,
      capture_id: `clip:${text.length}:${Date.now()}`,
    });
    if (resp.ok) {
      new Notification({ title: "Fleeting", body: `Captured${sourceTitle ? ` from ${sourceTitle}` : ""} (${text.length} chars)` }).show();
    } else {
      new Notification({ title: "Fleeting", body: `Capture failed: ${resp.status}` }).show();
    }
  } catch {
    new Notification({ title: "Fleeting", body: "Backend not running — capture failed" }).show();
  }
}

function alertFallback() {
  try {
    if (Notification.isSupported()) {
      new Notification({
        title: "Fleeting Dictation",
        body: "wtype unavailable. Transcribed text copied to clipboard.",
      }).show();
    }
  } catch {
    /* ignore notification errors */
  }
}

let lastTypedText = "";

async function handleTypeText(text) {
  if (hudWindow && !hudWindow.isDestroyed()) {
    hudWindow.hide();
  }
  if (!text || typeof text !== "string") return false;

  // Wait ~100ms for previous application focus restoration
  await new Promise((resolve) => setTimeout(resolve, 100));

  return new Promise((resolve) => {
    let settled = false;
    const settle = (success) => {
      if (!settled) {
        settled = true;
        resolve(success);
      }
    };

    let fallbackTriggered = false;
    const handleFallback = () => {
      if (fallbackTriggered) return;
      fallbackTriggered = true;
      fallbackCopy(text).then((copied) => {
        alertFallback();
        settle(copied);
      });
    };

    const wtypeBin = fs.existsSync("/usr/bin/wtype") ? "/usr/bin/wtype" : "wtype";
    let proc;
    try {
      proc = spawn(wtypeBin, ["--", text]);
    } catch {
      handleFallback();
      return;
    }

    proc.on("error", () => {
      handleFallback();
    });

    proc.on("exit", (code) => {
      if (code === 0) {
        settle(true);
      } else {
        handleFallback();
      }
    });
  });
}

function setupTray() {
  try {
    const iconFile = fs.existsSync(TRAY_ICON_PATH) ? TRAY_ICON_PATH : ICON_PATH;
    if (!fs.existsSync(iconFile)) return;
    const image = nativeImage.createFromPath(iconFile);
    tray = new Tray(image);
    tray.setToolTip("Fleeting — Local Memory & Activity Workbench");

    const menu = Menu.buildFromTemplate([
      {
        label: "Open Fleeting",
        click: () => {
          void showMainWindow();
        },
      },
      {
        label: "Quick Capture",
        click: () => {
          void showMainWindow("capture");
        },
      },
      {
        label: "Dictation HUD",
        accelerator: "CommandOrControl+Alt+Space",
        click: () => {
          void toggleHud();
        },
      },
      { type: "separator" },
      {
        label: "Inbox",
        click: () => {
          void showMainWindow("inbox");
        },
      },
      {
        label: "Activity Timeline",
        click: () => {
          void showMainWindow("timeline");
        },
      },
      {
        label: "Tasks",
        click: () => {
          void showMainWindow("tasks");
        },
      },
      { type: "separator" },
      {
        // #65 private mode: stop recording without touching the manual switch
        label: "Private for…",
        submenu: [15, 30, 60, 120].map((mins) => ({
          label: `${mins} minutes`,
          click: () => {
            apiPost("/api/activity/private", { minutes: mins })
              .then((r) => {
                if (r.ok) new Notification({ title: "Fleeting", body: `Private for ${mins} minutes` }).show();
              })
              .catch(() =>
                new Notification({ title: "Fleeting", body: "Backend not running — private mode off" }).show(),
              );
          },
        })),
      },
      {
        label: "Quit Fleeting",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]);
    tray.setContextMenu(menu);
    tray.on("click", () => {
      if (!mainWindow || mainWindow.isDestroyed()) {
        void showMainWindow();
        return;
      }
      if (mainWindow.isVisible() && mainWindow.isFocused()) {
        mainWindow.hide();
      } else {
        void showMainWindow();
      }
    });
  } catch {
    /* tray not supported in some minimal compositors */
  }
}

// Single-instance lock
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", (_event, argv) => {
    if (argv.includes("--hud")) {
      void toggleHud();
      return;
    }
    const target = argv.includes("--capture") ? "capture" : undefined;
    void showMainWindow(target);
  });

  app.on("activate", () => {
    void showMainWindow();
  });

  app.whenReady().then(async () => {
    authToken = apiToken();

    // Auto-grant microphone & clipboard permissions for local app
    session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
      const allowed = ["media", "clipboard-read", "clipboard-sanitized-write", "notifications"];
      callback(allowed.includes(permission));
    });

    ipcMain.handle("window:minimize", () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.minimize();
      }
    });
    ipcMain.handle("window:toggle-maximize", () => {
      if (!mainWindow || mainWindow.isDestroyed()) return false;
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
        return false;
      }
      mainWindow.maximize();
      return true;
    });
    ipcMain.handle("window:close", () => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.close();
      }
    });
    ipcMain.handle("window:is-maximized", () => {
      if (!mainWindow || mainWindow.isDestroyed()) return false;
      return mainWindow.isMaximized();
    });
    ipcMain.handle("shell:open-external", (_e, url) => {
      if (typeof url === "string" && (url.startsWith("http://") || url.startsWith("https://"))) {
        return shell.openExternal(url);
      }
    });

    // HUD IPC Handlers
    ipcMain.handle("hud:hide", () => {
      if (hudWindow && !hudWindow.isDestroyed()) {
        hudWindow.hide();
      }
    });
    ipcMain.handle("hud:resize", (_event, height) => {
      if (hudWindow && !hudWindow.isDestroyed() && typeof height === "number") {
        hudWindow.setSize(520, Math.round(height));
      }
    });
    ipcMain.handle("hud:type-text", (_event, text) => handleTypeText(text));
    ipcMain.handle("hud:undo-last-type", () => handleUndoLastType());
    ipcMain.handle("hud:active-app", async () => {
      const raw = await runCmd("hyprctl", ["activewindow", "-j"]);
      try {
        const data = JSON.parse(raw);
        return data.class || data.appClass || null;
      } catch {
        return null;
      }
    });
    // #34: capture the live window so a task can record where it can be done.
    ipcMain.handle("window:active", async () => {
      const raw = await runCmd("hyprctl", ["activewindow", "-j"]);
      try {
        const data = JSON.parse(raw);
        return { app: data.class || data.appClass || null, title: data.title || null };
      } catch {
        return { app: null, title: null };
      }
    });

    // Register global shortcut
    try {
      globalShortcut.register("CommandOrControl+Alt+Space", () => {
        toggleHud();
      });
      globalShortcut.register("CommandOrControl+Alt+Backspace", () => {
        void handleUndoLastType();
      });
      globalShortcut.register("CommandOrControl+Alt+C", () => {
        void captureClipboard();
      });
    } catch {
      /* ignore shortcut registration failure */
    }

    setupTray();
    await createWindow();
    await createHudWindow();

    if (process.argv.includes("--hud")) {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.hide();
      }
      void toggleHud();
    }
  });
}

app.on("before-quit", () => {
  isQuitting = true;
  globalShortcut.unregisterAll();
  if (backendProc) {
    try {
      backendProc.kill("SIGTERM");
    } catch {
      /* ignore */
    }
    backendProc = null;
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin" || isQuitting) {
    app.quit();
  }
});
