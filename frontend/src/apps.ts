import { getActivePaletteId, getPaletteColors, type ChartPaletteId } from "./chartPalettes";

/** Deterministic, balanced colors for application charts and activity views. */

const KNOWN_COLORS: Record<string, string> = {
  zcode: "#786b8a",
  "google-chrome": "#55708a",
  chromium: "#4b786b",
  firefox: "#9b6a3f",
  antigravity: "#bd5d38",
  fleeting: "#60784f",
  "org.omarchy.terminal": "#4b786b",
  kitty: "#557d78",
  alacritty: "#74875c",
  code: "#55708a",
  obsidian: "#786b8a",
  slack: "#a34e49",
  discord: "#5b7180",
  spotify: "#557d78",
};

const KNOWN_LABELS: Record<string, string> = {
  zcode: "ZCode",
  "google-chrome": "Google Chrome",
  chromium: "Chromium",
  firefox: "Firefox",
  "brave-origin": "Brave Browser",
  antigravity: "Antigravity",
  fleeting: "Fleeting",
  "org.omarchy.terminal": "Terminal",
  "org.omarchy.btop": "System Monitor",
  "org.gnome.nautilus": "Files",
  "xdg-desktop-portal-gtk": "Desktop Portal",
  code: "VS Code",
  obsidian: "Obsidian",
  kitty: "Kitty",
  alacritty: "Alacritty",
  wezterm: "WezTerm",
  ghostty: "Ghostty",
  spotify: "Spotify",
  discord: "Discord",
  slack: "Slack",
  steam: "Steam",
  zen: "Zen Browser",
};

export function appColor(name: string, overridePalette?: ChartPaletteId): string {
  const activeId = overridePalette ?? getActivePaletteId();
  const colors = getPaletteColors(activeId);
  const key = (name || "").toLowerCase().trim();

  // If on default palette, preserve handcrafted recognized app branding colors
  if (activeId === "default" && KNOWN_COLORS[key]) {
    return KNOWN_COLORS[key];
  }

  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return colors[h % colors.length];
}

export function prettyAppName(appClass: string): string {
  const raw = (appClass || "").trim();
  if (!raw) return "Unknown";
  const low = raw.toLowerCase();
  if (KNOWN_LABELS[low]) return KNOWN_LABELS[low];

  // Handle Chromium/Chrome PWA classes like chrome-web.whatsapp.com__-Default or chrome-127.0.0.1__-Default
  if (low.startsWith("chrome-")) {
    const host = low.replace(/^chrome-/, "").replace(/__-.*$/, "");
    if (host.includes("whatsapp")) return "WhatsApp Web";
    if (host.includes("127.0.0.1") || host.includes("localhost")) return "Local Web App";
    const segs = host.split(".").filter((s) => s && s !== "www" && s !== "web" && s !== "com");
    if (segs.length > 0) {
      return segs[0].replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) + " Web";
    }
  }

  // Strip reverse-DNS prefixes like org.omarchy.xyz or com.spotify.Client
  const parts = raw.split(".");
  const tail = parts.length > 1 ? parts[parts.length - 1] : raw;
  return tail
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function appMonogram(appClass: string): string {
  const pretty = prettyAppName(appClass);
  const words = pretty.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  const clean = pretty.replace(/[^a-zA-Z0-9]/g, "");
  return clean.slice(0, 2).toUpperCase() || "AP";
}

export function fmtSecs(seconds: number): string {
  if (seconds <= 0) return "0m";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))}s`;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${h}h` : `${h}h ${String(rem).padStart(2, "0")}m`;
}
