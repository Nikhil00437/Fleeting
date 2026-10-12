import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SystemTab from "../settings/SystemTab";
import type { HealthStatus, Settings } from "../../types";

/** #390: the runtime metrics panel.
 *
 * Rendered with no metrics — which is the SSR/no-network path and the one that
 * actually runs in the node-environment suite — so the assertions are about the
 * fallback, which is the part that must never be blank or misleading. The
 * numbers themselves are asserted against the backend, in Python.
 */

const settings = { config_path: "/home/u/.config/fleeting/config.toml" } as Settings;

const health = {
  ok: true,
  version: "0.1.0",
  db: true,
  queue: 0,
  uptime_secs: 10,
} as unknown as HealthStatus;

const noop = () => {};

function render() {
  return renderToStaticMarkup(
    <SystemTab
      health={health}
      s={settings}
      onToast={noop}
      loadAll={noop}
      embedding={null}
      onBackfill={noop}
      backfillBusy={false}
    />,
  );
}

describe("runtime metrics panel (#390)", () => {
  it("names its window rather than showing bare numbers", () => {
    // An unqualified "12" is meaningless; the user has to know it is today.
    expect(render()).toContain("Last 24 hours");
  });

  it("says so when metrics are unavailable, instead of showing zeros", () => {
    // The tempting failure is rendering 0/0ms/0% because the fetch has not
    // landed. On a local app that reads as "everything is fine", which is the
    // one thing a metrics panel must not do when it does not know.
    const html = render();
    expect(html).toContain("Not available.");
    expect(html).not.toContain("0%");
  });

  it("still renders the rest of the tab without metrics", () => {
    expect(render()).toContain('data-testid="copy-diagnostics"');
  });
});