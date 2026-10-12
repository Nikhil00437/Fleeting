/// <reference types="playwright/test" />
import { defineConfig, devices } from "@playwright/test";

/**
 * #190, the half Playwright was actually needed for: a real browser against a
 * real server and a real database.
 *
 * Deliberately chromium-only and against the FastAPI server rather than the
 * Vite dev server. The backend already serves `frontend/dist` and proxies
 * nothing — mounting the app in front of it exercises the same wiring a user
 * gets, including `_mount_frontend`, which nothing else covers. Electron is not
 * launched: the window lifecycle is Electron's to test, and a mock of it would
 * only assert the mock was called.
 *
 * The server runs against `.demo/` via XDG, seeded by #189, with the LLM and
 * the activity collector off. Without that config the run starts a vault
 * watcher on the real ~/Documents/FleetingVault — the path that once mirrored
 * test notes into it and imported ~440 back as captures.
 */

const PORT = Number(process.env.E2E_PORT || 7427);
const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const DEMO = `${ROOT}/.demo`;

export default defineConfig({
  testDir: "./e2e",
  // One worker: the seeded database is shared state, and these tests write to
  // it. Parallelism would make the live-update assertions depend on which
  // worker happened to be looking.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? "line" : [["list"]],
  timeout: 20_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // The HUD is a dictation bar and will not render past its error state
        // without a microphone: `getUserMedia` fails headless, so `CaptureHud`
        // shows "Not supported" and none of its real UI is reachable. These
        // give Chromium a synthetic input device — a real MediaStream and a
        // real MediaRecorder, which a hand-rolled stub cannot provide, since
        // `new MediaRecorder(fakeStream)` throws.
        launchOptions: {
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
          ],
        },
        permissions: ["microphone"],
      },
    },
  ],
  webServer: {
    // `scripts/e2e-server.sh` seeds and starts it, so the database is the same
    // deterministic one #394 will screenshot.
    command: `${ROOT}/scripts/e2e-server.sh`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});