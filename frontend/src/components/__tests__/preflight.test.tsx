import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import PreflightCard from "../PreflightCard";
import { describePreflight, missingRequired } from "../preflight";
import type { PreflightCheck } from "../../types";

function check(over: Partial<PreflightCheck> = {}): PreflightCheck {
  return {
    name: "ffmpeg",
    ok: false,
    required: false,
    detail: "not on PATH",
    fix: "apt install ffmpeg",
    ...over,
  };
}

describe("preflight summary", () => {
  it("leads with what is actually broken", () => {
    const line = describePreflight([
      check({ name: "vault", ok: true, required: true, detail: "writable" }),
      check({ name: "ffmpeg" }),
      check({ name: "yt-dlp" }),
    ]);
    expect(line).toMatch(/ffmpeg/);
    expect(line).toMatch(/yt-dlp/);
  });

  it("says so when nothing is missing", () => {
    const line = describePreflight([
      check({ ok: true, detail: "ffmpeg 6.1" }),
      check({ name: "hyprctl", ok: true, detail: "Hyprland 0.45" }),
    ]);
    expect(line).toMatch(/everything/i);
    expect(line).not.toMatch(/missing/i);
  });

  it("does not list optional gaps as failures", () => {
    // ffmpeg missing is one broken feature; the vault is the whole app.
    const line = describePreflight([
      check({ name: "vault", ok: true, required: true }),
      check({ name: "ffmpeg" }),
    ]);
    // The distinction that matters: one broken feature is not a broken app.
    expect(line).toMatch(/optional/i);
    expect(line).not.toMatch(/cannot work/i);
  });

  it("counts required failures separately", () => {
    expect(
      missingRequired([
        check({ name: "vault", ok: false, required: true }),
        check({ name: "ffmpeg" }),
      ])
    ).toEqual(["vault"]);
  });

  it("survives an empty report", () => {
    // The endpoint is in a useEffect; a card that throws on first paint takes
    // the whole Diagnostics tab with it.
    expect(describePreflight([])).toBeTruthy();
    expect(missingRequired([])).toEqual([]);
  });
});

describe("PreflightCard", () => {
  it("shows the fix for anything missing", () => {
    const html = renderToStaticMarkup(
      <PreflightCard
        checks={[check({ name: "ffmpeg", fix: "apt install ffmpeg" }), check({ name: "hyprctl", ok: true })]}
      />
    );
    expect(html).toContain("apt install ffmpeg");
    expect(html).not.toContain("Hyprland-only"); // ok rows carry no fix
  });

  it("marks a required failure as such", () => {
    const html = renderToStaticMarkup(
      <PreflightCard checks={[check({ name: "vault", ok: false, required: true, fix: "set a vault" })]} />
    );
    expect(html).toContain("required");
  });

  it("renders nothing while loading rather than an empty box", () => {
    expect(renderToStaticMarkup(<PreflightCard checks={null} />)).toBe("");
  });

  it("shows an error instead of failing silently", () => {
    // A failed probe with no message is indistinguishable from "all good".
    const html = renderToStaticMarkup(<PreflightCard checks={null} error="network on fire" />);
    expect(html).toContain("network on fire");
  });

  it("is an ordered list so a screen reader announces the count", () => {
    const html = renderToStaticMarkup(<PreflightCard checks={[check(), check({ name: "yt-dlp" })]} />);
    expect(html).toContain("<ul");
    expect(html).toContain("<li");
  });
});