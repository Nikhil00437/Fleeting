import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SessionRibbon } from "../charts";
import type { ActivitySession } from "../../types";

vi.mock("../../api", () => ({ api: {} }));

const sessions: ActivitySession[] = [
  {
    id: 1,
    app_class: "zen",
    title: "reading docs",
    first_seen: "2026-10-04T09:00:00",
    last_seen: "2026-10-04T10:30:00",
    seconds: 5400,
    day: "2026-10-04",
  },
  {
    id: 2,
    app_class: "code",
    title: "fleeting",
    first_seen: "2026-10-04T11:00:00",
    last_seen: "2026-10-04T12:00:00",
    seconds: 3600,
    day: "2026-10-04",
  },
];

function render(onSelectApp?: (app: string) => void, selectedApp: string | null = null) {
  return renderToStaticMarkup(
    <SessionRibbon sessions={sessions} selectedApp={selectedApp} onSelectApp={onSelectApp} />,
  );
}

describe("SessionRibbon session blocks are keyboard reachable", () => {
  const interactive = render(() => {});

  it("renders each selectable block as a button", () => {
    // Two sessions, two interactive blocks.
    expect(interactive.match(/role="button"/g) ?? []).toHaveLength(2);
  });

  it("puts each block in the tab order", () => {
    expect(interactive.match(/tabindex="0"/g) ?? []).toHaveLength(2);
  });

  it("names each block with its readable app name and duration", () => {
    // prettyAppName turns "zen" into "Zen Browser" and "code" into "VS Code".
    expect(interactive).toContain('aria-label="Zen Browser, 1h 30m active"');
    expect(interactive).toContain('aria-label="VS Code, 1h active"');
  });

  it("does not make blocks focusable when there is nothing to select", () => {
    // No onSelectApp means the blocks are pure decoration.
    const plain = render(undefined);
    expect(plain).not.toContain('role="button"');
    expect(plain).not.toContain('tabindex="0"');
  });

  it("still renders the empty state", () => {
    const empty = renderToStaticMarkup(
      <SessionRibbon sessions={[]} onSelectApp={() => {}} />,
    );
    expect(empty).toContain("No tracked sessions");
  });
});