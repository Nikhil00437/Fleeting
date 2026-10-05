/**
 * @vitest-environment jsdom
 *
 * #2: hold-to-talk must record only while held — pointerDown starts the mic,
 * pointerUp stops and transcribes.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import CaptureHud from "../CaptureHud";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: { captureAudio: vi.fn(), templates: vi.fn().mockResolvedValue({}) },
}));

const start = vi.fn().mockResolvedValue(undefined);
const stop = vi.fn().mockResolvedValue(new Blob(["audio"], { type: "audio/webm" }));

vi.mock("../../hooks/useAudioVisualizer", () => ({
  useAudioVisualizer: vi.fn(() => ({
    isRecording: false,
    levels: [],
    elapsed: 0,
    error: null,
    start,
    stop,
    cancel: vi.fn(),
  })),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CaptureHud hold-to-talk", () => {
  it("starts on hold, transcribes on release", async () => {
    vi.mocked(api.captureAudio).mockResolvedValue({ raw_text: "hi there", title: "" } as never);
    render(<CaptureHud />);

    fireEvent.click(screen.getByTitle("Toggle hold-to-talk"));
    const hold = await screen.findByRole("button", { name: /hold to talk/i });

    start.mockClear();
    fireEvent.pointerDown(hold);
    expect(start).toHaveBeenCalledTimes(1);

    fireEvent.pointerUp(hold);
    await vi.waitFor(() => expect(stop).toHaveBeenCalled());
    await vi.waitFor(() => expect(api.captureAudio).toHaveBeenCalled());
  });
});
