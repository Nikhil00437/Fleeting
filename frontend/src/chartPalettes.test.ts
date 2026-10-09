/**
 * @vitest-environment jsdom
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  CHART_PALETTES,
  getActivePaletteId,
  getPaletteColors,
  setActivePaletteId,
} from "./chartPalettes";
import { appColor } from "./apps";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

describe("chartPalettes (#175)", () => {
  it("defaults to Studio Ember palette", () => {
    expect(getActivePaletteId()).toBe("default");
    const colors = getPaletteColors();
    expect(colors).toEqual(CHART_PALETTES.default.colors);
  });

  it("stores and retrieves colorblind-safe Okabe-Ito palette", () => {
    setActivePaletteId("okabe_ito");
    expect(getActivePaletteId()).toBe("okabe_ito");
    const colors = getPaletteColors();
    expect(colors).toEqual(CHART_PALETTES.okabe_ito.colors);
    // Verified 8 colors in Okabe-Ito
    expect(colors).toHaveLength(8);
  });

  it("supports Viridis and High-Contrast palettes", () => {
    setActivePaletteId("viridis");
    expect(getActivePaletteId()).toBe("viridis");
    expect(getPaletteColors()).toEqual(CHART_PALETTES.viridis.colors);

    setActivePaletteId("high_contrast");
    expect(getActivePaletteId()).toBe("high_contrast");
    expect(getPaletteColors()).toEqual(CHART_PALETTES.high_contrast.colors);
  });

  it("appColor uses active palette colors when non-default palette selected", () => {
    setActivePaletteId("okabe_ito");
    const color = appColor("custom_app_123");
    expect(CHART_PALETTES.okabe_ito.colors).toContain(color);
  });
});
