import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import ErrorBoundary, { describeError, errorHeadline } from "../ErrorBoundary";

describe("error headline", () => {
  it("is a readable sentence", () => {
    expect(errorHeadline(new Error("Cannot read properties of undefined"))).toBe(
      "Something went wrong",
    );
  });

  it("does not leak a stack trace into the UI", () => {
    const msg = describeError(new Error("x"), "rendering chart");
    expect(msg).toContain("rendering chart");
    expect(msg).not.toContain("at ");
  });

  it("handles a thrown non-Error", () => {
    expect(describeError("plain string", "saving")).toContain("plain string");
    expect(describeError(undefined, "saving")).toContain("saving");
  });

  it("never returns an empty description", () => {
    expect(describeError(new Error(""), "ctx").length).toBeGreaterThan(0);
  });
});

describe("catching and rendering the fallback", () => {
  // renderToStaticMarkup cannot trigger a render throw, so drive the same
  // static React calls directly: getDerivedStateFromError captures, and the
  // resulting state renders the fallback.
  it("records the error via getDerivedStateFromError", () => {
    const next = ErrorBoundary.getDerivedStateFromError(new Error("boom"));
    expect(next?.error).toBeInstanceOf(Error);
  });

  it("renders an alert with recovery actions instead of blanking", () => {
    const b = new ErrorBoundary({ children: null, context: "rendering chart" });
    b.state = { error: new Error("bad tick data"), attempt: 0 };

    const html = renderToStaticMarkup(b.render());

    expect(html).toContain('role="alert"');
    expect(html).toContain("Try again");
    expect(html).toContain("Reload app");
    // Reassures the user their local notes are fine.
    expect(html).toMatch(/stored locally/);
    expect(html).toContain("rendering chart");
  });

  it("renders children when there is no error", () => {
    const b = new ErrorBoundary({ children: <p>hello</p> });
    expect(renderToStaticMarkup(b.render())).toContain("hello");
  });

  it("logs the error for the console rather than swallowing it", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const b = new ErrorBoundary({ children: null });
    b.componentDidCatch(new Error("boom"), {
      componentStack: "in App",
    } as never);
    expect(spy).toHaveBeenCalled();
    expect(String(spy.mock.calls[0][0])).toMatch(/render error/);
    spy.mockRestore();
  });
});