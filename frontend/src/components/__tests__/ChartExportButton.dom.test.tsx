/**
 * @vitest-environment jsdom
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ChartExportButton from "../ChartExportButton";
import * as chartExportModule from "../chartExport";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ChartExportButton component (#253)", () => {
  it("renders export button and toggles export menu", () => {
    const dummySvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    render(<ChartExportButton title="Test Metric" getSvg={() => dummySvg} />);

    const btn = screen.getByRole("button", { name: /Export Test Metric chart/i });
    expect(btn).toBeTruthy();
    expect(btn.getAttribute("aria-expanded")).toBe("false");

    // Click to open
    fireEvent.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");

    const pngOption = screen.getByRole("menuitem", { name: /PNG/i });
    const svgOption = screen.getByRole("menuitem", { name: /SVG/i });
    expect(pngOption).toBeTruthy();
    expect(svgOption).toBeTruthy();

    // Click outside to close
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menuitem", { name: /PNG/i })).toBeNull();
  });

  it("triggers export with selected format", async () => {
    const exportSpy = vi.spyOn(chartExportModule, "exportSvgElement").mockResolvedValue();
    const dummySvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");

    render(<ChartExportButton title="Weekly Focus" getSvg={() => dummySvg} />);

    const btn = screen.getByRole("button", { name: /Export Weekly Focus chart/i });
    fireEvent.click(btn);

    const svgOption = screen.getByRole("menuitem", { name: /SVG/i });
    fireEvent.click(svgOption);

    expect(exportSpy).toHaveBeenCalledWith(dummySvg, "weekly_focus", "svg");
  });
});
