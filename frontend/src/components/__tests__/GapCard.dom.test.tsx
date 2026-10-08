// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import GapCard from "../GapCard";
import { api } from "../../api";
import type { ActivityGap } from "../../types";

const gap = (over: Partial<ActivityGap> = {}): ActivityGap => ({
  start: "2026-10-08T13:00:00",
  end: "2026-10-08T16:30:00",
  minutes: 210,
  ...over,
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const render_ = (gaps: ActivityGap[], onToast = vi.fn(), onFilled = vi.fn()) => {
  const view = render(<GapCard gaps={gaps} onToast={onToast} onFilled={onFilled} />);
  return { onToast, onFilled, unmount: view.unmount };
};

describe("GapCard (#337)", () => {
  it("renders nothing when the day has no holes", () => {
    const { container } = render(<GapCard gaps={[]} onToast={vi.fn()} onFilled={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("summarises one gap and several gaps differently", () => {
    const { unmount } = render_([gap()]);
    expect(screen.getByText(/Away 3h30m/)).toBeTruthy();
    unmount();
    render_([gap(), gap({ minutes: 45 })]);
    expect(screen.getByText(/2 gaps, 4h15m total/)).toBeTruthy();
  });

  it("fills the longest gap with what the user typed", async () => {
    const { onToast, onFilled } = render_([gap()]);
    const fill = vi.spyOn(api, "fillGap").mockResolvedValue({ id: 1 } as never);

    fireEvent.click(screen.getByText("Fill a gap"));
    fireEvent.change(screen.getByLabelText("What were you doing"), {
      target: { value: "offsite interview" },
    });
    fireEvent.click(screen.getByText("Record it"));

    await waitFor(() => expect(fill).toHaveBeenCalledWith("2026-10-08T13:00:00", 30, "offsite interview"));
    expect(onToast).toHaveBeenCalledWith("Gap filled in");
    expect(onFilled).toHaveBeenCalled();
  });

  it("asks for the note before calling the API", () => {
    const { onToast } = render_([gap()]);
    const fill = vi.spyOn(api, "fillGap").mockResolvedValue({ id: 1 } as never);

    fireEvent.click(screen.getByText("Fill a gap"));
    fireEvent.click(screen.getByText("Record it"));

    expect(fill).not.toHaveBeenCalled();
    expect(onToast).toHaveBeenCalledWith("Say what you were doing first", "err");
  });

  it("keeps the form open when the API refuses", async () => {
    const { onToast, onFilled } = render_([gap()]);
    vi.spyOn(api, "fillGap").mockRejectedValue(new Error("that time is not inside a recorded gap"));

    fireEvent.click(screen.getByText("Fill a gap"));
    fireEvent.change(screen.getByLabelText("What were you doing"), { target: { value: "x" } });
    fireEvent.click(screen.getByText("Record it"));

    await waitFor(() =>
      expect(onToast).toHaveBeenCalledWith("that time is not inside a recorded gap", "err"),
    );
    expect(onFilled).not.toHaveBeenCalled();
  });
});