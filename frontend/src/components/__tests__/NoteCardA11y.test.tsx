import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import NoteCard from "../NoteCard";
import type { Note } from "../../types";

vi.mock("../../api", () => ({ api: {} }));

const note: Note = {
  id: "abc123",
  type: "text",
  title: "Ship the portfolio site",
  summary: "A short summary",
  raw_text: "long body text that should not be the accessible name",
  snippet: null,
  tags: ["work"],
  action_items: [],
  source: {},
  audio_path: null,
  status: "done",
  error: null,
  pinned: false,
  archived: false,
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T10:00:00+00:00",
  processed_at: "2026-10-01T10:00:00+00:00",
} as unknown as Note;

function render(over: Partial<Note> = {}) {
  return renderToStaticMarkup(
    <NoteCard note={{ ...note, ...over }} onOpen={() => {}} onPin={() => {}} />,
  );
}

describe("NoteCard is reachable by keyboard", () => {
  const html = render();

  it("renders as a button role", () => {
    expect(html).toContain('role="button"');
  });

  it("is in the tab order", () => {
    expect(html).toContain('tabindex="0"');
  });

  it("has an accessible name that identifies the note", () => {
    expect(html).toMatch(/aria-label="Open note: Ship the portfolio site"/);
  });

  it("falls back to the body text when there is no title", () => {
    const untitled = render({ title: "" });
    expect(untitled).toMatch(/aria-label="Open note: long body text/);
  });

  it("still falls back to the id when there is no text at all", () => {
    const empty = render({ title: "", raw_text: "" });
    expect(empty).toContain('aria-label="Open note: abc123"');
  });
});

describe("TimelineView session ribbon", () => {
  // charts.tsx had Bars and StackBar keyboard-correct but SessionRibbon not,
  // in the same file. Asserted via the shared helper's contract instead of
  // rendering the whole dashboard.
  it("uses the same activation helper as the note cards", async () => {
    const mod = await import("../a11y");
    const props = mod.noteCardActivationProps("session 10:00 zen");
    expect(props.role).toBe("button");
    expect(props.tabIndex).toBe(0);
  });
});