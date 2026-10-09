/**
 * @vitest-environment jsdom
 */

import { describe, expect, it, vi } from "vitest";
import { exportSvgElement } from "../chartExport";

describe("chartExport utility (#253)", () => {
  it("exports an SVG element as vector SVG", async () => {
    // Create an SVG element in jsdom
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", "50");
    circle.setAttribute("cy", "50");
    circle.setAttribute("r", "40");
    svg.appendChild(circle);
    document.body.appendChild(svg);

    const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = vi.fn();
    window.URL.createObjectURL = createObjectURL;
    window.URL.revokeObjectURL = revokeObjectURL;

    let clicked = false;
    const origCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreateElement(tag);
      if (tag === "a") {
        el.click = () => {
          clicked = true;
        };
      }
      return el;
    });

    await exportSvgElement(svg, "test_chart", "svg");

    expect(createObjectURL).toHaveBeenCalled();
    expect(clicked).toBe(true);

    document.body.removeChild(svg);
  });
});
