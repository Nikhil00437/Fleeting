/**
 * These tests need a real DOM.
 *
 * Every other frontend test in this repo renders through
 * `renderToStaticMarkup`, which emits attributes but never runs effects or
 * dispatches events. That covers "does it contain X" and nothing else — so the
 * whole async surface of the app (fetch on mount, SSE, click handlers, error
 * boundaries) was untestable.
 *
 * `@vitest-environment jsdom` is opted into per file rather than set globally,
 * so the ~170 static-markup tests keep running in `node` and stay fast.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import ErrorBoundary from "../ErrorBoundary";
import NoteCard from "../NoteCard";
import type { Note } from "../../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error("render blew up");
  return <p>all good</p>;
}

describe("ErrorBoundary catches a real render throw", () => {
  it("shows the fallback instead of unmounting the tree", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary context="rendering the dashboard">
        <Boom explode />
      </ErrorBoundary>,
    );

    // Previously: nothing. The whole app went to a blank white screen.
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Something went wrong/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Try again/i })).toBeTruthy();
    expect(screen.getByText(/rendering the dashboard/)).toBeTruthy();
  });

  it("reassures the user their notes are safe", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    );
    expect(screen.getByText(/stored locally/i)).toBeTruthy();
  });

  it("renders children untouched when nothing throws", () => {
    render(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("all good")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps showing the fallback when retry still throws", () => {
    // Honest behaviour: retrying while the cause persists re-catches. The
    // alternative — pretending to recover — would be a lie with a blank screen
    // behind it.
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Try again/i }));
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("recovers once the cause is gone", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeTruthy();

    // The cause is fixed, *then* the user retries.
    rerender(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Try again/i }));
    expect(screen.getByText("all good")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

const note = {
  id: "n1",
  type: "text",
  title: "Ship the portfolio site",
  summary: "",
  raw_text: "body",
  tags: [],
  action_items: [],
  source: {},
  status: "done",
  error: null,
  pinned: false,
  archived: false,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  processed_at: null,
} as unknown as Note;

describe("NoteCard responds to the keyboard", () => {
  it("opens on Enter", () => {
    const onOpen = vi.fn();
    render(<NoteCard note={note} onOpen={onOpen} onPin={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /Ship the portfolio site/ }));
    expect(onOpen).toHaveBeenCalledWith("n1");
  });

  it("opens on Space, which a div would otherwise ignore", () => {
    const onOpen = vi.fn();
    render(<NoteCard note={note} onOpen={onOpen} onPin={() => {}} />);
    const card = screen.getByRole("button", { name: /Ship the portfolio site/ });
    fireEvent.keyDown(card, { key: " " });
    expect(onOpen).toHaveBeenCalledWith("n1");
  });

  it("ignores keys that are not activations", () => {
    const onOpen = vi.fn();
    render(<NoteCard note={note} onOpen={onOpen} onPin={() => {}} />);
    const card = screen.getByRole("button", { name: /Ship the portfolio site/ });
    for (const key of ["a", "Escape", "Tab", "ArrowDown"]) {
      fireEvent.keyDown(card, { key });
    }
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("is reachable by Tab", () => {
    render(<NoteCard note={note} onOpen={() => {}} onPin={() => {}} />);
    expect(screen.getByRole("button", { name: /Ship the portfolio site/ }).tabIndex).toBe(0);
  });
});
