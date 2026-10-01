const {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  Tray,
  nativeImage,
  session,
  shell,
} = require("electron");
const { spawn } = require("child_process");
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

let mainWindow = null;
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
    icon: fs.existsSync(ICON_PATH) ? ICON_PATH : undefined,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  });

  if (state.maximized) {
    mainWindow.maximize();
  }

  mainWindow.on("maximize", () => {
    mainWindow?.webContents.send("window:maximized", true);
    saveWindowState(mainWindow);
  });
  mainWindow.on("unmaximize", () => {
    mainWindow?.webContents.send("window:maximized", false);
    saveWindowState(mainWindow);
  });
  mainWindow.on("resize", () => saveWindowState(mainWindow));
  mainWindow.on("move", () => saveWindowState(mainWindow));
  mainWindow.on("close", () => saveWindowState(mainWindow));

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
          if (!mainWindow) return;
          mainWindow.show();
          mainWindow.focus();
        },
      },
      {
        label: "Quick Capture",
        click: () => {
          if (!mainWindow) return;
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send("app:navigate", "capture");
        },
      },
      { type: "separator" },
      {
        label: "Inbox",
        click: () => {
          mainWindow?.show();
          mainWindow?.focus();
          mainWindow?.webContents.send("app:navigate", "inbox");
        },
      },
      {
        label: "Activity Timeline",
        click: () => {
          mainWindow?.show();
          mainWindow?.focus();
          mainWindow?.webContents.send("app:navigate", "timeline");
        },
      },
      {
        label: "Tasks",
        click: () => {
          mainWindow?.show();
          mainWindow?.focus();
          mainWindow?.webContents.send("app:navigate", "tasks");
        },
      },
      { type: "separator" },
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
      if (!mainWindow) return;
      if (mainWindow.isVisible() && mainWindow.isFocused()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
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
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
      if (argv.includes("--capture")) {
        mainWindow.webContents.send("app:navigate", "capture");
      }
    }
  });

  app.whenReady().then(async () => {
    // Auto-grant microphone & clipboard permissions for local app
    session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
      const allowed = ["media", "clipboard-read", "clipboard-sanitized-write", "notifications"];
      callback(allowed.includes(permission));
    });

    ipcMain.handle("window:minimize", () => mainWindow?.minimize());
    ipcMain.handle("window:toggle-maximize", () => {
      if (!mainWindow) return false;
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
        return false;
      }
      mainWindow.maximize();
      return true;
    });
    ipcMain.handle("window:close", () => mainWindow?.close());
    ipcMain.handle("window:is-maximized", () => mainWindow?.isMaximized() ?? false);
    ipcMain.handle("shell:open-external", (_e, url) => {
      if (typeof url === "string" && (url.startsWith("http://") || url.startsWith("https://"))) {
        return shell.openExternal(url);
      }
    });

    setupTray();
    await createWindow();
  });
}

app.on("before-quit", () => {
  isQuitting = true;
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
