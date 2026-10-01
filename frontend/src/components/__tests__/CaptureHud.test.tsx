import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import CaptureHud, { formatElapsed, calculateBarHeight } from "../CaptureHud";

// Mock api
vi.mock("../../api", () => ({
  api: {
    captureAudio: vi.fn(),
  },
}));

// Mock useAudioVisualizer
vi.mock("../../hooks/useAudioVisualizer", () => ({
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

describe("CaptureHud Component & Helpers", () => {
  const originalWindow = globalThis.window;
  const originalDocument = globalThis.document;

  beforeEach(() => {
    vi.clearAllMocks();

    const mockDesktop = {
      isElectron: true,
      platform: "linux",
      minimize: vi.fn().mockResolvedValue(undefined),
      toggleMaximize: vi.fn().mockResolvedValue(false),
      close: vi.fn().mockResolvedValue(undefined),
      isMaximized: vi.fn().mockResolvedValue(false),
      openExternal: vi.fn().mockResolvedValue(undefined),
      onMaximizeChange: vi.fn().mockReturnValue(() => {}),
      onNavigate: vi.fn().mockReturnValue(() => {}),
      hideHud: vi.fn().mockResolvedValue(undefined),
      resizeHud: vi.fn().mockResolvedValue(undefined),
      typeText: vi.fn().mockResolvedValue(true),
      onHudTrigger: vi.fn().mockReturnValue(() => {}),
    };

    // Provide node-safe mock window
    globalThis.window = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      setTimeout: setTimeout.bind(globalThis),
      clearTimeout: clearTimeout.bind(globalThis),
      setInterval: setInterval.bind(globalThis),
      clearInterval: clearInterval.bind(globalThis),
      fleetingDesktop: mockDesktop,
    } as unknown as Window & typeof globalThis;

    // Provide node-safe mock document
    globalThis.document = {
      body: {
        classList: {
          add: vi.fn(),
          remove: vi.fn(),
        },
      },
    } as unknown as Document;
  });

  afterEach(() => {
    globalThis.window = originalWindow;
    globalThis.document = originalDocument;
  });

  describe("formatElapsed", () => {
    it("formats 0 seconds as 0:00", () => {
      expect(formatElapsed(0)).toBe("0:00");
    });

    it("formats single digit seconds with leading zero (e.g. 0:04)", () => {
      expect(formatElapsed(4)).toBe("0:04");
      expect(formatElapsed(9)).toBe("0:09");
    });

    it("formats double digit seconds without extra zeros", () => {
      expect(formatElapsed(42)).toBe("0:42");
    });

    it("formats minutes and seconds accurately", () => {
      expect(formatElapsed(65)).toBe("1:05");
      expect(formatElapsed(600)).toBe("10:00");
    });
  });

  describe("calculateBarHeight", () => {
    it("returns minHeight for level 0", () => {
      expect(calculateBarHeight(0)).toBe(3);
    });

    it("returns maxHeight for level 1", () => {
      expect(calculateBarHeight(1)).toBe(20);
    });

    it("clamps negative levels to minHeight", () => {
      expect(calculateBarHeight(-0.5)).toBe(3);
    });

    it("clamps levels greater than 1 to maxHeight", () => {
      expect(calculateBarHeight(2.5)).toBe(20);
    });

    it("handles non-finite values safely", () => {
      expect(calculateBarHeight(NaN)).toBe(3);
      expect(calculateBarHeight(Infinity)).toBe(3);
    });

    it("scales intermediate levels proportionally", () => {
      // 3 + 0.5 * 17 = 11.5 -> rounds to 12
      expect(calculateBarHeight(0.5)).toBe(12);
    });
  });

  describe("CaptureHud Render", () => {
    it("renders the floating HUD pill with wave bars and timer in listening state", () => {
      const html = renderToStaticMarkup(<CaptureHud />);
      expect(html).toContain("hud-pill");
      expect(html).toContain("sdot");
      expect(html).toContain("swave");
      expect(html).toContain("0:04");
      expect(html).toContain("Dictate");
    });

    it("renders 9 wave bar elements", () => {
      const html = renderToStaticMarkup(<CaptureHud />);
      const barMatches = html.match(/style="height:\d+px"/g);
      expect(barMatches).not.toBeNull();
      expect(barMatches?.length).toBe(9);
    });

    it("renders cancel and commit action buttons", () => {
      const html = renderToStaticMarkup(<CaptureHud />);
      expect(html).toContain("Stop &amp; transcribe (Enter)");
      expect(html).toContain("Cancel capture (Esc)");
    });

    it("renders error state when microphone access fails", async () => {
      const { useAudioVisualizer } = await import("../../hooks/useAudioVisualizer");
      vi.mocked(useAudioVisualizer).mockReturnValueOnce({
        isRecording: false,
        levels: Array(9).fill(0),
        elapsed: 0,
        error: "Microphone permission denied",
        start: vi.fn().mockRejectedValue(new Error("Microphone permission denied")),
        stop: vi.fn().mockResolvedValue(null),
        cancel: vi.fn(),
      });

      const html = renderToStaticMarkup(<CaptureHud />);
      expect(html).toContain("Microphone permission denied");
      expect(html).toContain("Retry");
    });

    it("renders note mode when initialMode is set to note", () => {
      const html = renderToStaticMarkup(<CaptureHud initialMode="note" />);
      expect(html).toContain("Note");
    });

    it("renders processing state with spinner and Whisper message", () => {
      const html = renderToStaticMarkup(<CaptureHud initialState="processing" />);
      expect(html).toContain("sspinner");
      expect(html).toContain("Transcribing with Whisper…");
    });

    it("renders preview state with checkmark and status label", () => {
      const html = renderToStaticMarkup(<CaptureHud initialState="preview" initialMode="dictate" />);
      expect(html).toContain("Typed at cursor");
      expect(html).toContain("Closing…");
    });

    it("renders preview state for note mode with Fleeting vault message", () => {
      const html = renderToStaticMarkup(<CaptureHud initialState="preview" initialMode="note" />);
      expect(html).toContain("Saved to Fleeting vault");
    });
  });
});
