import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import NoteDrawer from "../NoteDrawer";

vi.mock("../../api", () => ({
  api: {
    collections: vi.fn().mockResolvedValue([]),
    noteLinks: vi.fn().mockResolvedValue({ outgoing: [], backlinks: [] }),
    noteVersions: vi.fn().mockResolvedValue([]),
    noteCollections: vi.fn().mockResolvedValue([]),
    attachments: vi.fn().mockResolvedValue([]),
    templates: vi.fn().mockResolvedValue({}),
  },
}));

const note: any = {
  id: "n1",
  type: "text",
  title: "t",
  summary: "",
  raw_text: "body",
  tags: [],
  action_items: [],
  source: {},
  audio_path: null,
  status: "done",
  error: null,
  pinned: false,
  archived: false,
  fields: { rating: 4, url: "https://example.com" },
  created_at: "2026-10-05T10:00:00Z",
  updated_at: "2026-10-05T10:00:00Z",
};

describe("NoteDrawer custom fields (#471)", () => {
  it("renders ad-hoc fields even without a template schema", () => {
    const html = renderToStaticMarkup(
      <NoteDrawer note={note} onClose={() => {}} onUpdate={() => {}} onDelete={() => {}} onToast={() => {}} />,
    );
    expect(html).toContain("Custom fields");
    expect(html).toContain("rating");
    expect(html).toContain('value="https://example.com"');
  });
});
