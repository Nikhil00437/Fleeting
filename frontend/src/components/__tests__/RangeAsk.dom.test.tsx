// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import RangeAsk from "../RangeAsk";
import { api } from "../../api";
import type { WindowAnswer } from "../../types";

const answer = (over: Partial<WindowAnswer> = {}): WindowAnswer => ({
  day: "2026-10-08",
  start: "2026-10-08T09:00:00",
  end: "2026-10-08T10:00:00",
  question: "",
  answer: "2 sessions, 1h tracked.",
  used_llm: false,
  sessions: [],
  ...over,
});

const track = (
  el: HTMLElement,
  from: number,
  to: number,
): { start: number; width: number } => {
  const rect = { left: 0, width: 1000, top: 0, bottom: 16, height: 16, right: 1000, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  vi.spyOn(el, "getBoundingClientRect").mockReturnValue(rect);
  fireEvent.mouseDown(el, { clientX: from * 1000, clientY: 0 });
  fireEvent.mouseMove(el, { clientX: to * 1000, clientY: 0 });
  fireEvent.mouseUp(el);
  return { start: from, width: to - from };
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function setup() {
  vi.spyOn(api, "askWindow").mockResolvedValue(answer());
  const onToast = vi.fn();
  const { container } = render(<RangeAsk day="2026-10-08" onToast={onToast} onOpenNote={() => {}} />);
  const track_ = container.querySelector(".cursor-crosshair") as HTMLElement;
  return { track: track_, onToast };
}

describe("RangeAsk (#63)", () => {
  it("asks about the dragged range with the typed question", async () => {
    const { track: strip } = setup();
    vi.spyOn(api, "askWindow").mockResolvedValue(answer());

    fireEvent.change(screen.getByLabelText("Question about the selected stretch"), {
      target: { value: "was I reviewing PRs?" },
    });
    track(strip, 0.375, 0.5); // 09:00–12:00
    fireEvent.click(screen.getByText("Ask"));

    await waitFor(() =>
      expect(api.askWindow).toHaveBeenCalledWith(
        "2026-10-08",
        "2026-10-08T09:00:00",
        "2026-10-08T12:00:00",
        "was I reviewing PRs?",
      ),
    );
  });

  it("cannot ask before a range is chosen", () => {
    const { track: strip } = setup();
    expect(screen.getByText("Ask")).toHaveProperty("disabled", true);
    void strip;
  });

  it("shows the answer and the sessions behind it", async () => {
    const { track: strip } = setup();
    vi.spyOn(api, "askWindow").mockResolvedValue(
      answer({
        answer: "1 sessions, 30m tracked.",
        sessions: [
          {
            id: 4,
            app_class: "kitty",
            title: "vim",
            first_seen: "2026-10-08T09:10:00",
            last_seen: "2026-10-08T09:40:00",
            seconds: 1800,
            project: "fleeting",
            note: null,
          },
        ],
      }),
    );

    track(strip, 0.375, 0.45);
    fireEvent.click(screen.getByText("Ask"));

    expect(await screen.findByText("1 sessions, 30m tracked.")).toBeTruthy();
    expect(screen.getByText(/kitty · vim/)).toBeTruthy();
  });

  it("reports a rejected range and stays quiet", async () => {
    const { track: strip, onToast } = setup();
    vi.spyOn(api, "askWindow").mockRejectedValue(new Error("the range must sit inside the day"));

    track(strip, 0.375, 0.45);
    fireEvent.click(screen.getByText("Ask"));

    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith("the range must sit inside the day", "err"),
    );
    expect(screen.queryByText(/sessions,/)).toBeNull();
  });
});