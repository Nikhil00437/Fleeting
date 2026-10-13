import { describe, expect, it } from "vitest";
import { remoteStylesheets, describeOffline } from "../offline";
import type { OfflineReport } from "../../types";

const report: OfflineReport = {
  offline: false,
  features: [
    { name: "llm", enabled: false, network: "none", detail: "no model configured" },
    {
      name: "youtube",
      enabled: true,
      network: "remote",
      detail: "yt-dlp fetches the video and audio over the network",
    },
  ],
};

describe("remoteStylesheets", () => {
  it("finds a cross-origin stylesheet at runtime", () => {
    // The point of this is to report the font fetch without hardcoding it, so
    // the number goes down by itself if the fonts are ever vendored.
    const sheets = [
      { href: "http://127.0.0.1:7425/assets/index.css" },
      { href: "https://fonts.googleapis.com/css2?family=Inter" },
    ];
    expect(remoteStylesheets(sheets as CSSStyleSheet[], "http://127.0.0.1:7425")).toEqual([
      "https://fonts.googleapis.com/css2?family=Inter",
    ]);
  });

  it("treats a same-origin sheet as local", () => {
    const sheets = [{ href: "http://127.0.0.1:7425/assets/index.css" }];
    expect(remoteStylesheets(sheets as CSSStyleSheet[], "http://127.0.0.1:7425")).toEqual([]);
  });

  it("does not throw when there are no stylesheets", () => {
    // Runs during first paint; a throw here takes the Diagnostics tab with it.
    expect(remoteStylesheets([], "http://127.0.0.1:7425")).toEqual([]);
    expect(remoteStylesheets(undefined, "http://127.0.0.1:7425")).toEqual([]);
  });
});

describe("describeOffline", () => {
  it("says plainly when nothing leaves the machine", () => {
    // Every feature local. Reusing `report` here would keep youtube remote and
    // test nothing.
    const local = { ...report, features: report.features.map((f) => ({ ...f, network: "none" as const })) };
    expect(describeOffline(local.features)).toMatch(/nothing leaves/i);
  });

  it("names what leaves and where it goes", () => {
    const line = describeOffline(report.features);
    expect(line).toContain("youtube");
  });

  it("does not claim offline when a remote feature is on", () => {
    // The sentence is the whole deliverable; if it can be wrong, the page is
    // worse than no page.
    expect(describeOffline(report.features)).not.toMatch(/nothing leaves/i);
  });
});