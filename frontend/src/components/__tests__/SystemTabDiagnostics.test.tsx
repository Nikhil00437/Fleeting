import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SystemTab from "../settings/SystemTab";
import type { HealthStatus, Settings } from "../../types";

/** #395: the button has to exist, say what it does, and not be armed on mount.
 *
 * `renderToStaticMarkup` rather than a DOM test because this is a question
 * about markup and wiring, not about effects — the click behaviour is covered
 * by the backend tests plus the fact that the handler is the only thing that
 * can call `api.diagnostics`.
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

describe("diagnostics bundle button (#395)", () => {
  it("is present", () => {
    expect(render()).toContain('data-testid="copy-diagnostics"');
  });

  it("tells the user secrets are removed", () => {
    // The most important sentence on the button. Someone is about to paste
    // this into a public issue; "it is safe" must be visible before the click,
    // not in a tooltip they may never find.
    const html = render();
    expect(html).toContain("&lt;set&gt;");
    expect(html.toLowerCase()).toContain("replaced");
  });

  it("is idle on mount", () => {
    expect(render()).not.toContain("Gathering");
  });

  it("explains what is in it", () => {
    const html = render();
    expect(html).toContain("Version");
    expect(html.toLowerCase()).toContain("bug report");
  });
});