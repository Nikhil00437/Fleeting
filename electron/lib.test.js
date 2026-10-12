// #190: coverage for the parts of the Electron shell that do not need Electron.
//
// `main.cjs` calls `app.commandLine.appendSwitch` and `app.setName` at module
// load, so importing it into any test runner fails before a single assertion
// runs. 722 lines of real logic — bearer-token handling, window-state
// persistence, the health probe — sat behind that, untested and untestable in
// place.
//
// So the logic moved to `lib.cjs`, which requires nothing but node builtins,
// and `main.cjs` imports it. One source of truth, not a copy: if these tests
// pass and `main.cjs` drifted, the tray would be sending unauthenticated POSTs
// while the suite stayed green.
//
// What is deliberately NOT here: anything needing a real BrowserWindow. The
// window lifecycle is Electron's to test, and a mock of it would only assert
// that the mock was called.

import { describe, expect, it, beforeEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  readApiToken,
  authHeaders,
  loadWindowState,
  saveWindowState,
  runCmd,
  DEFAULT_WINDOW_STATE,
} from "./lib.cjs";

let dir;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "fleeting-electron-"));
});

describe("readApiToken", () => {
  it("reads api_token from the activity section", () => {
    const f = join(dir, "config.toml");
    writeFileSync(f, '[activity]\napi_token = "secret123"\nenabled = true\n');
    expect(readApiToken(f)).toBe("secret123");
  });

  it("is empty when the file does not exist", () => {
    expect(readApiToken(join(dir, "nope.toml"))).toBe("");
  });

  it("is empty when there is no token", () => {
    const f = join(dir, "config.toml");
    writeFileSync(f, "[activity]\nenabled = true\n");
    expect(readApiToken(f)).toBe("");
  });

  // The whole point of scoping the match to the section: a token belonging to
  // some other setting must never be sent as a bearer credential for /api.
  it("ignores api_token in another section", () => {
    const f = join(dir, "config.toml");
    writeFileSync(
      f,
      '[llm]\napi_token = "wrong-section"\n\n[activity]\nenabled = true\n',
    );
    expect(readApiToken(f)).toBe("");
  });

  it("survives a file it cannot read", () => {
    const f = join(dir, "config.toml");
    writeFileSync(f, '[activity]\napi_token = "x"\n');
    expect(readApiToken(dir)).toBe(""); // a directory, not a file
  });
});

describe("authHeaders", () => {
  it("omits Authorization entirely when there is no token", () => {
    // Not `Bearer ` with an empty value: some servers treat that as a
    // configured-but-wrong credential and reject a request a local client
    // should have been allowed to make.
    expect(authHeaders("")).toEqual({ "Content-Type": "application/json" });
  });

  it("attaches the bearer token when there is one", () => {
    expect(authHeaders("secret123")).toEqual({
      "Content-Type": "application/json",
      Authorization: "Bearer secret123",
    });
  });
});

describe("window state", () => {
  it("falls back to defaults when there is no file", () => {
    expect(loadWindowState(join(dir, "absent.json"))).toEqual(DEFAULT_WINDOW_STATE);
  });

  it("falls back to defaults on corrupt JSON", () => {
    // A truncated write must not brick the launcher on every subsequent start.
    const f = join(dir, "state.json");
    writeFileSync(f, '{"width": 1360, "height"');
    expect(loadWindowState(join(dir, "state.json"))).toEqual(DEFAULT_WINDOW_STATE);
  });

  it("round-trips through a save", () => {
    const f = join(dir, "nested", "state.json");
    saveWindowState(f, { width: 800, height: 600, x: 12, y: 34, maximized: true });
    expect(loadWindowState(f)).toEqual({
      width: 800,
      height: 600,
      x: 12,
      y: 34,
      maximized: true,
    });
  });

  it("creates the directory it writes into", () => {
    const f = join(dir, "a", "b", "state.json");
    saveWindowState(f, { width: 1, height: 2 });
    expect(readFileSync(f, "utf8")).toContain('"width":1');
  });

  it("fills in a missing geometry rather than writing null", () => {
    // A maximized window has no bounds; writing those out would restore an
    // off-screen window the next time it is un-maximized.
    const f = join(dir, "state.json");
    saveWindowState(f, { maximized: true, width: 1360, height: 860 });
    const got = loadWindowState(f);
    expect(got.width).toBe(1360);
    expect(got.height).toBe(860);
  });
});

describe("runCmd", () => {
  it("returns stdout on success", async () => {
    await expect(runCmd("echo", ["hello"], 2000)).resolves.toBe("hello\n");
  });

  it("returns an empty string when the command is missing", async () => {
    // wl-paste and hyprctl are absent on plenty of machines. A capture hotkey
    // must degrade, not crash the shell.
    await expect(runCmd("definitely-not-a-real-binary-xyz", [], 2000)).resolves.toBe("");
  });

  it("returns an empty string on a non-zero exit", async () => {
    await expect(runCmd("sh", ["-c", "exit 3"], 2000)).resolves.toBe("");
  });

  it("returns an empty string rather than hanging past the timeout", async () => {
    await expect(runCmd("sleep", ["5"], 150)).resolves.toBe("");
  });
});