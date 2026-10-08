// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import RewindBar from "../RewindBar";
import type { ActivitySession } from "../../types";

const session = (id: number, hh: number, minutes = 1800, title = "vim"): ActivitySession =>
  ({
    id,
    app_class: "kitty",
    title,
    first_seen: `2026-10-08T${String(hh).padStart(2, "0")}:00:00`,
    last_seen: `2026-10-08T${String(hh).padStart(2, "0")}:30:00`,
    seconds: minutes,
    day: "2026-10-08",
  }) as ActivitySession;

const sessions = [session(1, 9), session(2, 13), session(3, 20)];

const scrubTo = (minutes: number) => {
  const slider = screen.getByLabelText("Rewind position") as HTMLInputElement;
  fireEvent.change(slider, { target: { value: String(minutes) } });
};

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("RewindBar (#341)", () => {
  it("shows the whole day until the user scrubs", () => {
    render(<RewindBar sessions={sessions} />);
    expect(screen.getByText(/whole day/)).toBeTruthy();
    expect(screen.getByText("1h 30m")).toBeTruthy();
  });

  it("renders nothing for a day with no sessions", () => {
    const { container } = render(<RewindBar sessions={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("counts only what had happened by the cursor", () => {
    render(<RewindBar sessions={sessions} />);
    // the slider steps in 5-minute increments, so land on a step
    scrubTo(13 * 60 + 30);

    expect(screen.getByText(/by/)).toBeTruthy();
    expect(screen.getByText("13:30")).toBeTruthy();
    expect(screen.getByText("1h")).toBeTruthy(); // two 30-minute stretches
    expect(screen.getByText(/across 2 sessions/)).toBeTruthy();
  });

  it("lists the sessions so far, newest first", () => {
    render(<RewindBar sessions={sessions} />);
    scrubTo(13 * 60 + 30);
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toHaveLength(2);
    expect(items[0]).toContain("13:00");
  });

  it("replays the day when play is pressed", () => {
    render(<RewindBar sessions={sessions} />);
    fireEvent.click(screen.getByLabelText("Replay the day"));
    expect(screen.getByLabelText("Pause the replay")).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(750);
    });
    expect(screen.getByText("00:30")).toBeTruthy();
  });

  it("stops at the end of the day", () => {
    render(<RewindBar sessions={sessions} />);
    scrubTo(23 * 60 + 50);
    fireEvent.click(screen.getByLabelText("Replay the day"));
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByText("24:00")).toBeTruthy();
    expect(screen.getByLabelText("Replay the day")).toBeTruthy();
  });

  it("goes back to the whole day", () => {
    render(<RewindBar sessions={sessions} />);
    scrubTo(600);
    fireEvent.click(screen.getByText("Whole day"));
    expect(screen.getByText(/whole day/)).toBeTruthy();
  });
});