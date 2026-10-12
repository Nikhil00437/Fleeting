import { test, expect } from "@playwright/test";

/**
 * #190, the half Playwright was actually needed for: a real browser, a real
 * server, a real database and a real event stream.
 *
 * The backend has 5700+ pytest tests through `TestClient` and the frontend has
 * 528 through `renderToStaticMarkup` and jsdom. Neither exercises the wiring
 * between them — `_mount_frontend`, real `fetch`, and the SSE stream.
 *
 * Markers are unique per run. That is load-bearing, not tidy: the seeded
 * database is reused across runs, so a fixed `capture_id` means the note
 * already exists before the test starts, the initial `GET /api/notes` shows it,
 * and the assertion passes without the event stream being involved at all.
 *
 * Selectors are accessible names, not test ids. `NoteCard` renders
 * `Open note: <title>`, so these assertions double as a check that the list is
 * reachable by screen reader.
 */

const marker = `E2E-LIVE-${Math.random().toString(36).slice(2, 8)}`;

test("the served SPA boots and lists the seeded notes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await page.goto("/");

  // One of the titles seed_demo writes. If this passes, the backend is serving
  // frontend/dist and the app mounted — neither of which any other test proves.
  // `.first()` because the seed cycles ten titles across twenty-eight notes.
  await expect(
    page.getByRole("button", { name: /Router firmware upgrade/ }).first(),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("a capture publishes note.created to the event stream", async ({ page, request }) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: /Router firmware upgrade/ }).first(),
  ).toBeVisible();

  // A second EventSource, alongside the app's own.
  //
  // Asserting on the rendered card instead would prove nothing about the
  // publish: the enricher fires `note.updated` a moment later and
  // `serverEvents.ts` upserts on that too, so the card appears whether or not
  // `note.created` was ever published. That version of this test passed with
  // the publish removed, and then again with the reducer branch removed.
  // AGENTS.md's claim is that every write the UI must see live must
  // `bus.publish(...)`, so the publish is what gets asserted.
  await page.evaluate(() => {
    const w = window as unknown as { __seen: string[] };
    w.__seen = [];
    const es = new EventSource("/api/events");
    es.addEventListener("message", (ev) => {
      w.__seen.push((JSON.parse((ev as MessageEvent).data) as { type: string }).type);
    });
  });

  const res = await request.post("/api/capture/text", {
    data: { text: `${marker}: the live path`, capture_id: `e2e-${marker}` },
  });
  expect(res.ok()).toBeTruthy();

  await expect
    .poll(
      () =>
        page.evaluate(() =>
          (window as unknown as { __seen: string[] }).__seen.filter(
            (t) => t === "note.created",
          ).length,
        ),
      { timeout: 10_000 },
    )
    .toBeGreaterThan(0);
});

test("a captured note shows up without a reload", async ({ page, request }) => {
  await page.goto("/");
  const tag = `${marker}-R`;
  expect(await page.getByRole("button", { name: new RegExp(tag) }).count()).toBe(0);

  await request.post("/api/capture/text", {
    data: { text: `${tag}: rendered path`, capture_id: `e2e-${tag}` },
  });

  // No reload, no navigation. If the write never reached the browser the card
  // would not appear until the user navigated away and back, which is the
  // symptom AGENTS.md describes.
  await expect(page.getByRole("button", { name: new RegExp(tag) })).toHaveCount(1, {
    timeout: 10_000,
  });
});

test("a repeated capture_id returns the original note", async ({ page, request }) => {
  const tag = `${marker}-IDEM`;
  const body = { text: `${tag}: same text`, capture_id: `e2e-${tag}` };

  const first = await request.post("/api/capture/text", { data: body });
  const second = await request.post("/api/capture/text", { data: body });
  expect(first.ok()).toBeTruthy();
  expect(second.ok()).toBeTruthy();

  // `.json()` is async; without the await this compares a Promise to an object.
  const [firstBody, secondBody] = [await first.json(), await second.json()];
  expect(secondBody).toMatchObject({ id: firstBody.id });

  await page.goto("/");
  // #332: one card, not two.
  await expect(page.getByRole("button", { name: new RegExp(tag) })).toHaveCount(1);
});

test("health is reported from the running backend", async ({ page }) => {
  await page.goto("/");
  const health = await page.request.get("/api/health");
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).db).toBe(true);
});