#!/usr/bin/env node
/**
 * #397: record a short demo of the app against the seeded demo database.
 *
 * Uses the same hermetic server as the e2e suite (`scripts/e2e-server.sh`), so
 * it needs no model, no collector and no vault — and the same deterministic
 * seed, so a re-record shows the same app.
 *
 * Kept out of the Playwright suite on purpose: this is not a test, it must not
 * run in CI, and a frame directory is not something to leave behind.
 */

import { spawn, execFileSync } from "node:child_process";
import { mkdirSync, rmSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = process.env.DEMO_PORT || 7428;
const OUT = process.argv.includes("--out") ? process.argv[process.argv.indexOf("--out") + 1] : join(ROOT, "assets");
const FRAMES = join(ROOT, ".demo-frames");

/** Scenes, in order. `act` runs after the page settles. */
const SCENES = [
  {
    name: "inbox",
    view: "/",
    settle: 2500,
    frames: 5,
  },
  {
    name: "capture-live",
    view: "/",
    settle: 2500,
    frames: 6,
    // The one thing a picture cannot show: a capture made elsewhere landing in
    // the inbox without a reload. This is the whole product.
    act: async (page) => {
      const token = `demo-${Math.random().toString(36).slice(2, 7)}`;
      // Absolute: `apiRequestContext` does not resolve a relative path the way
      // the browser does, and "/api/capture/text" raises "Invalid URL".
      await page.request.post(`http://127.0.0.1:${PORT}/api/capture/text`, {
        data: { text: `${token}: captured from the terminal, live in the inbox`, capture_id: `demo-${token}` },
      });
      return token;
    },
  },
  { name: "tasks", view: "/", settle: 1500, frames: 4, nav: "Tasks" },
  { name: "timeline", view: "/", settle: 1500, frames: 4, nav: "Timeline" },
  { name: "reports", view: "/", settle: 2000, frames: 5, nav: "Reports" },
];

async function waitForHealth(timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/api/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("server did not become healthy");
}

function startServer() {
  const child = spawn("bash", [join(ROOT, "scripts", "e2e-server.sh")], {
    env: { ...process.env, E2E_PORT: String(PORT) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let tail = "";
  const pump = (s) => {
    tail = (tail + s.toString()).split("\n").slice(-20).join("\n");
  };
  child.stdout.on("data", pump);
  child.stderr.on("data", pump);
  child.on("exit", (code) => {
    if (code) console.error(`server exited (${code}):\n${tail}`);
  });
  return child;
}

async function capture(page, scenes) {
  const taken = [];
  for (const scene of scenes) {
    await page.goto(`http://127.0.0.1:${PORT}${scene.view}`);
    if (scene.nav) {
      await page.getByRole("button", { name: scene.nav, exact: false }).first().click();
    }
    await page.waitForTimeout(scene.settle);

    // Wait for the view itself, not just the click: charts and lists fetch
    // after mount, and recording a half-mount gives a still frame of nothing.
    await page.evaluate(() =>
      [...document.querySelectorAll("svg")].map((e) => e.getBoundingClientRect().length),
    );
    await page.waitForTimeout(600);

    for (let f = 0; f < scene.frames; f += 1) {
      const file = join(FRAMES, `${String(taken.length).padStart(3, "0")}.png`);
      await page.screenshot({ path: file });
      taken.push({ file, scene });

      // Mid-scene action on the frame that follows the marker.
      if (scene.act && f === 1) {
        const token = await scene.act(page);
        // Hold on the result long enough to read it.
        await page.waitForTimeout(900);
        const after = join(FRAMES, `${String(taken.length).padStart(3, "0")}.png`);
        await page.screenshot({ path: after });
        taken.push({ file: after, scene, token });
      }
    }
  }
  return taken;
}

async function main() {
  const fps = Number(process.env.FPS || 2);
  const width = Number(process.env.WIDTH || 900);

  mkdirSync(OUT, { recursive: true });
  rmSync(FRAMES, { recursive: true, force: true });
  mkdirSync(FRAMES, { recursive: true });

  const server = startServer();
  try {
    await waitForHealth();
    const browser = await chromium.launch({
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
    });
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      deviceScaleFactor: 2,
    });
    const frames = await capture(page, SCENES);
    await browser.close();

    if (!frames.length) throw new Error("no frames captured");
    console.log(`captured ${frames.length} frames`);

    // One palette for the whole run. Per-segment palettes make the colour
    // banding you can see on a dark UI, and it is the only way a GIF of this
    // app looks like the app.
    const palette = join(FRAMES, "palette.png");
    execFileSync(
      "ffmpeg",
      ["-y", "-loglevel", "error", "-framerate", String(fps), "-i",
        join(FRAMES, "%03d.png"), "-vf", `palettegen=max_colors=${process.env.COLORS || 192}`, palette],
      { stdio: "inherit" },
    );
    execFileSync(
      "ffmpeg",
      ["-y", "-loglevel", "error", "-framerate", String(fps), "-i",
        join(FRAMES, "%03d.png"), "-i", palette,
        "-lavfi", `paletteuse=dither=bayer:bayer_scale=3,scale=${width}:-1:flags=lanczos`,
        "-loop", "0", join(OUT, "demo.gif")],
      { stdio: "inherit" },
    );

    console.log(`wrote ${join(OUT, "demo.gif")}`);
  } finally {
    server.kill("SIGTERM");
    if (process.env.KEEP_FRAMES !== "1") {
      rmSync(FRAMES, { recursive: true, force: true });
    } else {
      console.log(`frames kept in ${FRAMES}`);
    }
  }
}

main().catch((err) => {
  console.error(err && err.stack ? err.stack : err);
  process.exit(1);
});