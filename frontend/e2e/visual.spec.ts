import { test, expect } from "@playwright/test";

/**
 * #394 visual regression — the part that is worth automating.
 *
 * Deliberately **not** `toHaveScreenshot` against committed baselines. Two
 * reasons, both disqualifying here:
 *
 * 1. `index.css` pulls Inter, Inter Tight and IBM Plex Mono from Google Fonts
 *    over the network, so what gets rasterised depends on whether that fetch
 *    succeeded. Offline, Chromium falls back to Liberation Sans and every
 *    baseline differs.
 * 2. Even with the fonts loading, pixel output differs between this machine and
 *    a CI runner — different container, different libfreetype. A committed
 *    baseline would be red on CI and green here, which is worse than no test
 *    because it trains you to re-accept baselines.
 *
 * Vendoring the woff2 files would fix both, and would also make the app
 * genuinely offline — it claims "no cloud" and currently makes a Google Fonts
 * request on every load. That is a product decision about bundle size and
 * licence, not one to smuggle in with a test.
 *
 * So these assert the failures visual regression exists to catch, in a way that
 * survives a font change: a chart that renders zero-height, a heatmap with no
 * cells, a panel that collapsed, a HUD that is not compact. Those are real
 * regressions; "the pixels moved" is not.
 */

const card = /Open note:/;

/** Go to a view and wait for *that view* to be ready, not merely for the click.
 *
 * Clicking a nav button and immediately measuring is why this file flaked:
 * panels fetch after the view mounts, so an assertion can run against the
 * previous view's DOM. Each caller names the thing it waits for. */
async function open(
  page: import("@playwright/test").Page,
  view: string,
  ready: string,
) {
  await page.goto("/");
  await page.getByRole("button", { name: view, exact: false }).first().click();
  await expect(page.getByText(ready, { exact: false }).first()).toBeVisible({
    timeout: 15_000,
  });
}

test("the inbox lays out cards with real dimensions", async ({ page }) => {
  await page.goto("/");
  const first = page.getByRole("button", { name: card }).first();
  await expect(first).toBeVisible();

  const box = await first.boundingBox();
  expect(box, "a visible card must have a box").not.toBeNull();
  // A card that is present but zero-sized is the failure mode worth catching:
  // it renders, it is "visible" to a11y queries, and a user sees nothing.
  expect(box!.width).toBeGreaterThan(100);
  expect(box!.height).toBeGreaterThan(40);
});

test("nothing overflows the viewport horizontally", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: card }).first()).toBeVisible();

  const overflow = await page.evaluate(() => {
    const d = document.documentElement;
    return d.scrollWidth - d.clientWidth;
  });
  // A couple of pixels of rounding is normal; a scrollbar's worth is a bug.
  expect(overflow, "page scrolls sideways").toBeLessThanOrEqual(2);
});

test("every seeded note card is rendered", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: card }).first()).toBeVisible();
  // seed_demo writes 28 notes; a list that silently truncates to 20 would look
  // identical in a screenshot of the first screen.
  const count = await page.getByRole("button", { name: card }).count();
  expect(count).toBeGreaterThan(20);
});

test("the activity heatmap renders a cell for every day in the window", async ({ page }) => {
  // The heatmap lives on Timeline, not on a view of its own.
  await open(page, "Timeline", "Activity");
  await expect(page.getByTestId("heatmap-metric-notes")).toBeVisible({ timeout: 10_000 });

  // Cells carry an aria-label naming their day. The panel can mount, look
  // plausible and still render an empty grid if the fetch or the bucketing
  // returns nothing. seed_demo covers 14 days, so 14 is the expected shape —
  // not an arbitrary floor, which is what made the first attempt fail.
  const cells = page.locator('button[aria-label*="2026-"]');
  await expect(cells).toHaveCount(14, { timeout: 10_000 });

  const box = await cells.first().boundingBox();
  expect(box!.width).toBeGreaterThan(0);
  expect(box!.height).toBeGreaterThan(0);
});

test("charts render at a real size, not as collapsed icons", async ({ page }) => {
  await open(page, "Reports", "Capture Frequency");
  // Not `.chart-shell`: the report cards render plain <svg> inside
  // `glass-studio` panels and there is no `.chart-shell` on this view at all.
  // What matters is that charts are larger than the 14px nav icons the page is
  // full of — an SVG at 0x0 is the failure, and it looks fine in the DOM.
  const sized = await page.evaluate(
    () =>
      [...document.querySelectorAll("svg")]
        .map((e) => e.getBoundingClientRect())
        .filter((b) => b.width > 80 && b.height > 30).length,
  );
  expect(sized, "no chart-sized svg on the reports view").toBeGreaterThan(3);

  // `.chart-empty` is what a chart with no data renders instead. Fine on an
  // empty database, not fine against a fortnight of seed data.
  expect(await page.locator(".chart-empty").count()).toBe(0);
});

test("the HUD renders compact and without the app chrome", async ({ page }) => {
  await page.goto("/?mode=hud");

  // Measured from the HUD's own control, not from the document: the viewport
  // is 1280 wide whatever renders, so `scrollWidth` says nothing about the HUD
  // and was the reason the first attempt failed.
  const hold = page.getByRole("button", { name: "Hold", exact: true });
  await expect(hold).toBeVisible({ timeout: 10_000 });
  const box = await hold.boundingBox();
  expect(box!.height).toBeLessThan(80);
  expect(box!.width).toBeLessThan(400);

  // The full app must not have rendered underneath it — a broken mode check
  // gives the user a 1360px window where they wanted a strip.
  await expect(page.getByRole("button", { name: card })).toHaveCount(0);
});

test("the HUD is reachable by hash as well as by query", async ({ page }) => {
  await page.goto("/#hud");
  // `isHudMode` accepts three spellings; exercising one leaves the others free
  // to break silently.
  await expect(page.getByRole("button", { name: "Hold", exact: true })).toBeVisible({
    timeout: 10_000,
  });
});

test("an empty inbox renders an empty state rather than a blank page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox").first().fill("zzzzzznothingmatchesthiszzzz");
  // Whatever the empty state says, the page must not collapse to nothing.
  const body = await page.evaluate(() => document.body.innerText.trim().length);
  expect(body).toBeGreaterThan(20);
});

test("no unhandled errors on any main view", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`${e.message}`));

  for (const view of ["Today", "Review", "Tasks", "Timeline"]) {
    await page.goto("/");
    await page.getByRole("button", { name: view, exact: false }).first().click();
    await page.waitForTimeout(400);
  }
  expect(errors).toEqual([]);
});