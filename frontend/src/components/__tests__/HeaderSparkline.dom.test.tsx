/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import HeaderSparkline from "../HeaderSparkline";

afterEach(() => {
  cleanup();
});

describe("HeaderSparkline component (#254)", () => {
  it("renders accessible sparkline for point array", () => {
    const data = [
      { label: "Mon", value: 4 },
      { label: "Tue", value: 8 },
      { label: "Wed", value: 6 },
      { label: "Thu", value: 12 },
    ];

    render(
      <HeaderSparkline
        data={data}
        color="amber"
        label="4-day capture trend"
        unit="captures"
      />
    );

    const el = screen.getByRole("img");
    expect(el).toBeTruthy();
    expect(el.getAttribute("aria-label")).toContain("4-day capture trend");
    expect(el.getAttribute("aria-label")).toContain("total 30 captures");
    expect(el.getAttribute("aria-label")).toContain("latest 12");
  });

  it("renders fallback line when data is empty", () => {
    const { container } = render(<HeaderSparkline data={[]} />);
    const line = container.querySelector("line");
    expect(line).toBeTruthy();
  });

  it("handles mouse hover to show interactive popover tooltip", () => {
    const data = [
      { label: "Mon", value: 5 },
      { label: "Tue", value: 10 },
    ];

    render(
      <HeaderSparkline
        data={data}
        color="emerald"
        label="Completion velocity"
        unit="done"
      />
    );

    const svg = document.querySelector("svg");
    expect(svg).toBeTruthy();

    // Trigger mouse move on SVG
    if (svg) {
      fireEvent.mouseMove(svg, { clientX: 10, clientY: 10 });
    }

    // Expect tooltip content to appear
    expect(screen.getByText(/Mon:/i)).toBeTruthy();
  });

  it("works with raw number arrays", () => {
    render(<HeaderSparkline data={[2, 4, 6, 8]} color="sky" />);
    const el = screen.getByRole("img");
    expect(el).toBeTruthy();
    expect(el.getAttribute("aria-label")).toContain("latest 8");
  });
});
