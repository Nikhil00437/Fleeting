import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import App from "../App";

// Mock api
vi.mock("../api", () => ({
  api: {
    notes: vi.fn().mockResolvedValue([]),
    stats: vi.fn().mockResolvedValue({ total: 0, today: 0, week: 0, open_tasks: 0, done_tasks: 0, queue: 0, notes_per_day: [] }),
    activityDay: vi.fn().mockResolvedValue({ total_seconds: 0, apps: [], sessions: [] }),
    activityWeek: vi.fn().mockResolvedValue([]),
  },
}));

// Mock useAudioVisualizer
vi.mock("../hooks/useAudioVisualizer", () => ({
  useAudioVisualizer: vi.fn(() => ({
    isRecording: true,
    levels: [0, 0.2, 0.4, 0.6, 0.8, 1.0, 0.5, 0.25, 0],
    elapsed: 4,
    error: null,
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue(new Blob(["mock-audio"], { type: "audio/webm" })),
    cancel: vi.fn(),
  })),
}));

describe("App Mode Selection", () => {
  const originalWindow = globalThis.window;

  beforeEach(() => {
    globalThis.window = {
      location: {
        search: "",
        hash: "",
        pathname: "/",
      },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      setTimeout: setTimeout.bind(globalThis),
      clearTimeout: clearTimeout.bind(globalThis),
    } as unknown as Window & typeof globalThis;

    globalThis.EventSource = vi.fn().mockImplementation(() => ({
      close: vi.fn(),
      onmessage: null,
    })) as unknown as typeof EventSource;
  });

  afterEach(() => {
    globalThis.window = originalWindow;
  });

  it("renders CaptureHud exclusively when URL search contains ?mode=hud", () => {
    globalThis.window.location.search = "?mode=hud";

    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("capture-hud-root");
    expect(html).toContain("hud-pill");
    expect(html).not.toContain("NATIVE ELECTRON TITLEBAR");
    expect(html).not.toContain("3-PANE DESKTOP WORKBENCH");
  });

  it("renders CaptureHud exclusively when URL hash contains #hud", () => {
    globalThis.window.location.search = "";
    globalThis.window.location.hash = "#hud";

    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("capture-hud-root");
    expect(html).toContain("hud-pill");
    expect(html).not.toContain("3-PANE DESKTOP WORKBENCH");
  });

  it("renders main workbench when mode is not hud", () => {
    globalThis.window.location.search = "";
    globalThis.window.location.hash = "";

    const html = renderToStaticMarkup(<App />);
    expect(html).not.toContain("capture-hud-root");
    expect(html).toContain("Fleeting");
    expect(html).toContain("Workspace");
  });
});
