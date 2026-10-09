/** #112/#453 — what the assistant looked at, and what it ran. */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  describeTrace,
  summarizeContext,
} from "../assistantTrace";
import { AssistantTraceRow, ContextPreview } from "../AssistantTrace";
import type { LlmTrace } from "../../types";

describe("summarizeContext", () => {
  it("counts each kind of source", () => {
    expect(
      summarizeContext({ notes_count: 5, tasks_count: 3, logs_count: 0 }),
    ).toBe("5 notes, 3 tasks, no logs");
  });

  it("reports nothing retrieved without inventing zeros everywhere", () => {
    expect(
      summarizeContext({ notes_count: 0, tasks_count: 0, logs_count: 0 }),
    ).toBe("nothing retrieved");
  });
});

describe("describeTrace", () => {
  it("reports how many retrieval steps ran", () => {
    expect(
      describeTrace({
        id: "1",
        kind: "chat",
        queries: ["router", "router firmware", "firmware"],
        context: "",
        tool_calls: [],
        tokens: null,
        ms: 42,
        at: "2026-10-09T10:00:00+00:00",
      }),
    ).toBe("3 searches, no actions, 42ms");
  });

  it("counts the tools that ran", () => {
    expect(
      describeTrace({
        id: "1",
        kind: "chat",
        queries: ["q"],
        context: "",
        tool_calls: [{ tool: "create_task", params: { text: "x" } }],
        tokens: null,
        ms: 7,
        at: "2026-10-09T10:00:00+00:00",
      }),
    ).toBe("1 search, 1 action, 7ms");
  });
});

describe("AssistantTraceRow", () => {
  const trace: LlmTrace = {
    id: "1",
    kind: "chat",
    queries: ["router firmware", "firmware"],
    context: "=== Relevant Notes ===\n- [[note:abc|Router notes]]",
    tool_calls: [],
    tokens: null,
    ms: 42,
    at: "2026-10-09T10:00:00+00:00",
  };

  it("summarises the trace in the collapsed header", () => {
    const html = renderToStaticMarkup(
      <AssistantTraceRow trace={trace} expanded={false} onToggle={() => {}} />,
    );
    expect(html).toContain("2 searches");
    expect(html).toContain("42ms");
  });

  it("lists every query it actually issued, not just the typed one", () => {
    const html = renderToStaticMarkup(
      <AssistantTraceRow trace={trace} expanded onToggle={() => {}} />,
    );
    expect(html).toContain("router firmware");
    expect(html).toContain("firmware");
  });

  it("shows the exact context that was sent", () => {
    const html = renderToStaticMarkup(
      <AssistantTraceRow trace={trace} expanded onToggle={() => {}} />,
    );
    expect(html).toContain("Relevant Notes");
  });

  it("keeps the context out of the DOM while collapsed", () => {
    const html = renderToStaticMarkup(
      <AssistantTraceRow trace={trace} expanded={false} onToggle={() => {}} />,
    );
    expect(html).not.toContain("Relevant Notes");
  });

  it("is a real button so it is keyboard reachable", () => {
    const html = renderToStaticMarkup(
      <AssistantTraceRow trace={trace} expanded={false} onToggle={() => {}} />,
    );
    expect(html).toContain("<button");
    expect(html).toContain("aria-expanded=\"false\"");
  });
});

describe("ContextPreview", () => {
  const preview = {
    query: "router firmware",
    context: "=== Relevant Notes ===\n- [[note:abc|Router notes]]\n  Content: OpenWrt",
    sources: [
      { id: "abc", title: "Router notes", type: "text", kind: "note" as const, snippet: "OpenWrt" },
    ],
    context_used: { notes_count: 1, tasks_count: 0, logs_count: 0 },
    queries: ["router firmware"],
  };

  it("shows the retrieval summary", () => {
    const html = renderToStaticMarkup(<ContextPreview preview={preview} onClose={() => {}} />);
    expect(html).toContain("1 note");
  });

  it("shows the verbatim context block", () => {
    const html = renderToStaticMarkup(<ContextPreview preview={preview} onClose={() => {}} />);
    expect(html).toContain("OpenWrt");
  });

  it("names every source the model will see", () => {
    const html = renderToStaticMarkup(<ContextPreview preview={preview} onClose={() => {}} />);
    expect(html).toContain("Router notes");
  });

  it("says so plainly when nothing would be sent", () => {
    const html = renderToStaticMarkup(
      <ContextPreview
        preview={{ ...preview, context: "", sources: [], context_used: { notes_count: 0, tasks_count: 0, logs_count: 0 } }}
        onClose={() => {}}
      />,
    );
    expect(html).toContain("nothing");
  });
});
