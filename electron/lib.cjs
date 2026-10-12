/**
 * The parts of the Electron shell that need nothing but node builtins.
 *
 * Extracted from `main.cjs`, which cannot be imported by a test runner at all:
 * it calls `app.commandLine.appendSwitch` and `app.setName` at module load,
 * so 722 lines of real logic — bearer-token handling, window-state
 * persistence, the health probe — were unreachable from any test. `main.cjs`
 * imports these rather than reimplementing them, so there is one copy.
 *
 * Every function takes its file path or arguments as a parameter instead of
 * reading a module constant. That is what makes them testable: the real
 * callers pass `CONFIG_FILE`/`STATE_FILE`, the tests pass a temp path.
 */

const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const { execFile } = require("node:child_process");

const DEFAULT_WINDOW_STATE = { width: 1360, height: 860, maximized: false };

/**
 * Tray-originated writes hit the same host guard as the UI, so they need the
 * bearer token when one is configured. Read once at startup — this file is
 * tiny and the tray must not block on it per click.
 *
 * Scoped to `[activity]` deliberately: `api_token` under `[llm]` is a different
 * credential and must never be replayed as the activity token.
 */
function readApiToken(configFile) {
  try {
    const text = fs.readFileSync(configFile, "utf8");
    const section = text.match(/\[activity\]([\s\S]*?)(\n\[|$)/);
    const token = section && section[1].match(/^\s*api_token\s*=\s*"([^"]*)"/m);
    return token ? token[1] : "";
  } catch {
    return "";
  }
}

/**
 * `Authorization` is omitted rather than sent empty when there is no token:
 * `Bearer ` with a blank value reads as a configured-but-wrong credential,
 * which is a different failure from no credential.
 */
function authHeaders(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/** Defaults on a missing or corrupt file — a truncated write must not
 *  brick the launcher on every subsequent start. */
function loadWindowState(stateFile) {
  try {
    if (fs.existsSync(stateFile)) {
      const parsed = JSON.parse(fs.readFileSync(stateFile, "utf8"));
      if (parsed && typeof parsed === "object") return parsed;
    }
  } catch {
    /* ignore corrupt state */
  }
  return { ...DEFAULT_WINDOW_STATE };
}

/**
 * A maximized window reports no bounds, so the previous geometry is kept
 * rather than written out as null — otherwise un-maximizing later restores an
 * off-screen window.
 */
function saveWindowState(stateFile, state) {
  try {
    fs.mkdirSync(path.dirname(stateFile), { recursive: true });
    fs.writeFileSync(
      stateFile,
      JSON.stringify({
        width: state.width || DEFAULT_WINDOW_STATE.width,
        height: state.height || DEFAULT_WINDOW_STATE.height,
        x: state.x,
        y: state.y,
        maximized: Boolean(state.maximized),
      }),
    );
    return true;
  } catch {
    return false; // ignore write errors
  }
}

/** Never rejects and never hangs: the launcher polls this at startup. */
function probeHealth(backendUrl, timeoutMs = 1200) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      resolve(ok);
    };
    try {
      const req = http.get(`${backendUrl}/api/health`, { timeout: timeoutMs }, (res) => {
        res.resume();
        finish(res.statusCode === 200);
      });
      req.on("error", () => finish(false));
      req.on("timeout", () => {
        req.destroy();
        finish(false);
      });
    } catch {
      finish(false);
    }
  });
}

/**
 * Missing binaries are normal, not exceptional: wl-paste and hyprctl are
 * absent on plenty of machines and a capture hotkey must degrade rather than
 * take the shell down. Resolves to "" on any failure.
 */
function runCmd(cmd, args, timeoutMs = 2000) {
  return new Promise((resolve) => {
    try {
      execFile(cmd, args, { timeout: timeoutMs }, (err, stdout) =>
        resolve(err ? "" : String(stdout || "")),
      );
    } catch {
      resolve("");
    }
  });
}

module.exports = {
  DEFAULT_WINDOW_STATE,
  readApiToken,
  authHeaders,
  loadWindowState,
  saveWindowState,
  probeHealth,
  runCmd,
};