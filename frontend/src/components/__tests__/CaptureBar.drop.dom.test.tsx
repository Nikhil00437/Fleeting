/**
 * @vitest-environment jsdom
 *
 * #79: dropping text/URL/audio onto the capture bar captures it.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import CaptureBar from "../CaptureBar";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: { captureText: vi.fn(), captureYouTube: vi.fn(), captureAudio: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function setup() {
  const onCaptured = vi.fn();
  const onError = vi.fn();
  const utils = render(<CaptureBar inputRef={{ current: null }} onCaptured={onCaptured} onError={onError} />);
  return { onCaptured, onError, ...utils };
}

describe("CaptureBar drop capture", () => {
  it("dropped text becomes a capture", async () => {
    vi.mocked(api.captureText).mockResolvedValue({ id: "n1" } as never);
    const { container, onCaptured } = setup();
    fireEvent.drop(container.firstElementChild!, {
      dataTransfer: { files: [], getData: (t: string) => (t === "text/plain" ? "dropped thought" : "") },
    });
    await waitFor(() => expect(api.captureText).toHaveBeenCalledWith("dropped thought"));
    await waitFor(() => expect(onCaptured).toHaveBeenCalled());
  });

  it("dropped audio file routes to audio capture", async () => {
    vi.mocked(api.captureAudio).mockResolvedValue({ id: "n2" } as never);
    const { container } = setup();
    const file = new File(["fake-audio"], "memo.webm", { type: "audio/webm" });
    fireEvent.drop(container.firstElementChild!, {
      dataTransfer: { files: [file], getData: () => "" },
    });
    await waitFor(() => expect(api.captureAudio).toHaveBeenCalledWith(file, "memo.webm"));
  });

  it("dropped YouTube URL routes to youtube capture", async () => {
    vi.mocked(api.captureYouTube).mockResolvedValue({ id: "n3" } as never);
    const { container } = setup();
    fireEvent.drop(container.firstElementChild!, {
      dataTransfer: { files: [], getData: () => "https://youtu.be/dQw4w9WgXcQ" },
    });
    await waitFor(() => expect(api.captureYouTube).toHaveBeenCalledWith("https://youtu.be/dQw4w9WgXcQ"));
  });
});
