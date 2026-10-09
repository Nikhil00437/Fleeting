import { useEffect, useState } from "react";

export type ChartPaletteId = "default" | "okabe_ito" | "viridis" | "high_contrast";

export interface ChartPalette {
  id: ChartPaletteId;
  name: string;
  shortName: string;
  description: string;
  colors: string[];
}

export const CHART_PALETTES: Record<ChartPaletteId, ChartPalette> = {
  default: {
    id: "default",
    name: "Studio Ember",
    shortName: "Default",
    description: "Warm studio aesthetic (terracotta, slate, olive, teal)",
    colors: [
      "#bd5d38", // terracotta
      "#60784f", // olive leaf
      "#4b786b", // deep teal
      "#a34e49", // brick
      "#7d6b49", // brass
      "#55708a", // slate blue
      "#936b54", // clay
      "#557d78", // sea glass
      "#786b8a", // muted violet
      "#74875c", // sage
      "#9b6a3f", // ochre
      "#5b7180", // blue gray
    ],
  },
  okabe_ito: {
    id: "okabe_ito",
    name: "Colorblind-Safe (Okabe-Ito)",
    shortName: "Colorblind Safe",
    description: "Universally distinct colors for deuteranopia, protanopia & tritanopia",
    colors: [
      "#E69F00", // Orange
      "#56B4E9", // Sky Blue
      "#009E73", // Bluish Green
      "#F0E442", // Yellow
      "#0072B2", // Blue
      "#D55E00", // Vermilion
      "#CC79A7", // Reddish Purple
      "#999999", // Neutral Grey
    ],
  },
  viridis: {
    id: "viridis",
    name: "Viridis (Perceptually Uniform)",
    shortName: "Viridis",
    description: "Continuous perceptually uniform sequential scale, accessible across all vision types",
    colors: [
      "#440154", // Deep Violet
      "#414487", // Indigo
      "#2a788e", // Ocean Blue
      "#22a884", // Jade Green
      "#7ad151", // Spring Green
      "#fde725", // Bright Sun Yellow
    ],
  },
  high_contrast: {
    id: "high_contrast",
    name: "High Contrast (WCAG AAA)",
    shortName: "High Contrast",
    description: "Maximum luminance separation for low-vision and stark ambient light",
    colors: [
      "#ffffff", // Pure White
      "#ffff00", // Electric Yellow
      "#00e5ff", // Vivid Cyan
      "#ff0055", // Vivid Magenta
      "#00ff66", // Vivid Neon Green
      "#ff7700", // Vivid Orange
      "#b388ff", // Lavender Light
    ],
  },
};

const STORAGE_KEY = "fleeting_chart_palette";
const EVENT_NAME = "fleeting:chart-palette-change";

export function getActivePaletteId(): ChartPaletteId {
  if (typeof window === "undefined" || !window.localStorage) {
    return "default";
  }
  try {
    const val = window.localStorage.getItem(STORAGE_KEY) as ChartPaletteId | null;
    if (val && val in CHART_PALETTES) {
      return val;
    }
  } catch {
    // fallback
  }
  return "default";
}

export function setActivePaletteId(id: ChartPaletteId): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
    window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: id }));
  } catch {
    // fallback
  }
}

export function getPaletteColors(id?: ChartPaletteId): string[] {
  const effectiveId = id ?? getActivePaletteId();
  return CHART_PALETTES[effectiveId]?.colors ?? CHART_PALETTES.default.colors;
}

export function getPaletteColor(idx: number, id?: ChartPaletteId): string {
  const colors = getPaletteColors(id);
  return colors[Math.abs(idx) % colors.length];
}

/**
 * React hook to read and observe chart palette changes across components.
 */
export function useChartPalette() {
  const [paletteId, setPaletteIdState] = useState<ChartPaletteId>(getActivePaletteId);

  useEffect(() => {
    function onPaletteChange(e: Event) {
      const customEvent = e as CustomEvent<ChartPaletteId>;
      if (customEvent.detail && customEvent.detail in CHART_PALETTES) {
        setPaletteIdState(customEvent.detail);
      } else {
        setPaletteIdState(getActivePaletteId());
      }
    }

    window.addEventListener(EVENT_NAME, onPaletteChange);
    return () => {
      window.removeEventListener(EVENT_NAME, onPaletteChange);
    };
  }, []);

  const setPaletteId = (id: ChartPaletteId) => {
    setPaletteIdState(id);
    setActivePaletteId(id);
  };

  return {
    paletteId,
    setPaletteId,
    palette: CHART_PALETTES[paletteId],
    colors: CHART_PALETTES[paletteId].colors,
  };
}
