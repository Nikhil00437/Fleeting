// #458: the read-only demo banner's rendering.
//
// SSR-string rendering is the default in this project (see AGENTS.md): the
// component has no effects, so effects would prove nothing that markup does
// not.

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { DemoBanner, shouldShowDemoBanner } from "./DemoBanner";

describe("DemoBanner", () => {
 it("renders nothing when the app is not a demo", () => {
  expect(renderToStaticMarkup(<DemoBanner status={null} />)).toBe("");
  expect(
   renderToStaticMarkup(
    <DemoBanner status={{ demo_mode: false, reads_only: true, turn_off: "x" }} />,
   ),
  ).toBe("");
 });

 it("says so when the app is a demo", () => {
  const html = renderToStaticMarkup(
   <DemoBanner
    status={{ demo_mode: true, reads_only: true, turn_off: "server.demo_mode = false" }}
   />,
  );
  expect(html).toContain("Read-only demo");
  expect(html).toContain("role=\"status\"");
 });

 it("does not claim the value failed to load is a demo", () => {
  // A failed fetch means "unknown", and showing a demo banner on an unknown is
  // worse than showing nothing.
  expect(shouldShowDemoBanner(null)).toBe(false);
 });
});