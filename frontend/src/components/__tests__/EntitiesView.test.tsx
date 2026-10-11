/**
 * #258 the entity index.
 *
 * The extraction has existed since #411 and had no surface at all, so every
 * person in the inbox was reachable only by knowing the API. This is that
 * surface: a list you can read, and a person you can open.
 *
 * Node environment on purpose — like most tests here it renders to static
 * markup, so effects never run. The behaviour lives in the API layer and the
 * backend, both of which are tested directly.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { EntitiesView } from "../EntitiesView";
import type { EntityNote, EntityRow } from "../../types";

const PEOPLE: EntityRow[] = [
  { name: "Priya", mentions: 12, notes_count: 5, first_seen: "2026-09-01", last_seen: "2026-10-10" },
  { name: "Ben", mentions: 3, notes_count: 2, first_seen: "2026-08-01", last_seen: "2026-09-20" },
];

const NOTES: EntityNote[] = [
  { id: "n1", title: "call the clinic", summary: "about the results", type: "text", created_at: "2026-10-10T09:00:00" },
];

function render(entity: EntityRow[] | null, selected: string | null, notes: EntityNote[] | null) {
  return renderToStaticMarkup(
    <EntitiesView
      people={entity}
      selected={selected}
      notes={notes}
      loading={false}
      onSelect={() => {}}
      onBack={() => {}}
      onToast={() => {}}
      resolveAlias={async () => ({ ok: true })}
    />,
  );
}

describe("EntitiesView", () => {
  it("lists every person with how often they come up", () => {
    const html = render(PEOPLE, null, null);
    expect(html).toContain("Priya");
    expect(html).toContain("Ben");
    expect(html).toContain("12");
  });

  it("shows mentions and note counts as different numbers", () => {
    // One note naming Priya twice is two mentions and one note. Collapsing
    // them makes a person who is discussed a lot look widely mentioned.
    const html = render(PEOPLE, null, null);
    expect(html).toContain("12 mentions");
    expect(html).toContain("5 notes");
  });

  it("shows when each person was last seen", () => {
    expect(render(PEOPLE, null, null)).toContain("Last seen");
  });

  it("opens a person when one is selected", () => {
    const html = render(PEOPLE, "Priya", NOTES);
    expect(html).toContain("Priya");
    expect(html).toContain("call the clinic");
  });

  it("says plainly when nobody is mentioned yet", () => {
    const html = render([], null, null);
    expect(html).toMatch(/nothing/i);
  });

  it("does not render an empty box while loading", () => {
    const html = renderToStaticMarkup(
      <EntitiesView
        people={null}
        selected={null}
        notes={null}
        loading
        onSelect={() => {}}
        onBack={() => {}}
        onToast={() => {}}
        resolveAlias={async () => ({ ok: true })}
      />,
    );
    expect(html).toMatch(/loading|…|\.\.\./i);
  });

  it("a person with no notes is not a broken person", () => {
    const html = render(PEOPLE, "Ben", []);
    expect(html).toContain("Ben");
  });
});

vi.mock("../api", () => ({ api: { entitiesPeople: vi.fn(), entityNotes: vi.fn() } }));