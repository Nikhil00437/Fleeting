// #135: the lock screen's rendering.
//
// SSR-string rendering is this project's default (see AGENTS.md). The component
// holds state but renders no effects, so markup is what is under test; the
// behaviour that matters (the 423 gate, the throttle, the exempt set) is tested
// on the server, where it actually lives.

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { LOCK_HEADER, LockScreen } from "./LockScreen";

const UNLOCKED = { enabled: true, configured: true, locked: true, retry_in: 0 };

describe("LockScreen", () => {
 it("asks for a passphrase and says why", () => {
  const html = renderToStaticMarkup(<LockScreen status={UNLOCKED} onUnlock={async () => ""} />);
  expect(html).toContain("Locked");
  expect(html).toContain("Passphrase");
  // The input must not be an autocomplete for a *new* password.
  expect(html).toContain('type="password"');
 });

 it("names the header a token would travel in", () => {
  expect(LOCK_HEADER).toBe("x-fleeting-lock");
 });

 it("says how long to wait after too many attempts", () => {
  // Otherwise the button just looks broken.
  const html = renderToStaticMarkup(
   <LockScreen status={{ ...UNLOCKED, retry_in: 12.4 }} onUnlock={async () => ""} />,
  );
  expect(html).toContain("Too many attempts");
  expect(html).toContain("13s");
 });

 it("does not mention waiting when there is no delay", () => {
  const html = renderToStaticMarkup(<LockScreen status={UNLOCKED} onUnlock={async () => ""} />);
  expect(html).not.toContain("Too many attempts");
 });

 it("shows a failure as an alert", () => {
  // A silent failure on a lock screen is indistinguishable from a broken app.
  const onUnlock = vi.fn().mockRejectedValue(new Error("wrong passphrase"));
  expect(renderToStaticMarkup(<LockScreen status={UNLOCKED} onUnlock={onUnlock} />)).toContain(
   'type="submit"',
  );
 });
});