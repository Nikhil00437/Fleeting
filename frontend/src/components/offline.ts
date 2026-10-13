/** #460. The browser's half: the backend cannot see the web font the page
 * fetches from itself, so the SPA reports it here rather than the backend
 * claiming "nothing leaves this machine" while a Google Fonts request is in
 * flight. */

import type { OfflineFeature, OfflineReport } from "../types";

/** Stylesheets loaded from another origin, found at runtime.
 *
 * Discovered rather than hardcoded so the number drops by itself if the fonts
 * are ever vendored — a hardcoded "1 remote request" would quietly become a lie
 * the day someone fixed it.
 */
export function remoteStylesheets(
  sheets: CSSStyleSheet[] | undefined = typeof document === "undefined"
    ? []
    : Array.from(document.styleSheets),
  origin: string = typeof location === "undefined" ? "" : location.origin
): string[] {
  if (!sheets?.length || !origin) return [];
  return sheets
    .map((s) => s.href)
    .filter((href): href is string => !!href)
    .filter((href) => !href.startsWith(origin));
}

export function fontFeature(hrefs: string[]): OfflineFeature {
  return {
    name: "web fonts",
    enabled: hrefs.length > 0,
    network: hrefs.length ? "remote" : "none",
    detail: hrefs.length
      ? `fetched from ${new URL(hrefs[0]).host} on every page load`
      : "loaded from this machine",
  };
}

export function describeOffline(features: OfflineFeature[]): string {
  if (!features.length) return "Nothing leaves this machine.";
  const remote = features.filter((f) => f.network === "remote");
  if (!remote.length) return "Nothing leaves this machine.";
  return remote.length === 1
    ? `${remote[0].name} reaches the network: ${remote[0].detail}`
    : `${remote.length} things reach the network: ${remote.map((f) => f.name).join(", ")}`;
}

export function combine(
  backend: OfflineReport | null,
  remoteHrefs: string[]
): OfflineFeature[] {
  const base = backend?.features ?? [];
  return [...base, fontFeature(remoteHrefs)];
}
