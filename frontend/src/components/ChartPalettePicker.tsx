import { CHART_PALETTES, useChartPalette, type ChartPaletteId } from "../chartPalettes";
import { SlidersIcon } from "./Icons";

interface Props {
  className?: string;
  variant?: "inline" | "compact";
}

export default function ChartPalettePicker({ className = "", variant = "inline" }: Props) {
  const { paletteId, setPaletteId } = useChartPalette();

  const paletteEntries = Object.values(CHART_PALETTES);

  if (variant === "compact") {
    return (
      <div className={`inline-flex items-center gap-1.5 ${className}`}>
        <label htmlFor="chart-palette-select" className="text-xs text-ink-400 sr-only">
          Chart Palette
        </label>
        <select
          id="chart-palette-select"
          value={paletteId}
          onChange={(e) => setPaletteId(e.target.value as ChartPaletteId)}
          className="rounded-lg border border-white/[0.08] bg-zinc-900/90 px-2 py-1 text-xs text-ink-200 outline-none hover:border-white/20"
        >
          {paletteEntries.map((p) => (
            <option key={p.id} value={p.id}>
              {p.shortName}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div
      role="radiogroup"
      aria-label="Chart color palette selection"
      className={`space-y-2 ${className}`}
    >
      <div className="flex items-center gap-2">
        <SlidersIcon className="h-4 w-4 text-ink-400" />
        <span className="text-xs font-semibold text-ink-200">Accessible Chart Palettes</span>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {paletteEntries.map((p) => {
          const isSelected = paletteId === p.id;

          return (
            <button
              key={p.id}
              role="radio"
              aria-checked={isSelected}
              onClick={() => setPaletteId(p.id)}
              className={`flex flex-col gap-1.5 rounded-xl border p-3 text-left transition-all ${
                isSelected
                  ? "border-ember-500/50 bg-ember-500/[0.08] shadow-md ring-1 ring-ember-500/30"
                  : "border-white/[0.06] bg-white/[0.02] hover:border-white/[0.12] hover:bg-white/[0.04]"
              }`}
            >
              <div className="flex items-center justify-between">
                <span
                  className={`text-xs font-semibold ${
                    isSelected ? "text-ember-300" : "text-ink-200"
                  }`}
                >
                  {p.name}
                </span>
                {isSelected && (
                  <span className="rounded-full bg-ember-500/20 px-1.5 py-0.2 text-[10px] font-mono text-ember-300">
                    Active
                  </span>
                )}
              </div>

              <p className="text-[11px] leading-relaxed text-ink-400">{p.description}</p>

              {/* Color swatch row */}
              <div className="mt-1 flex items-center gap-1">
                {p.colors.slice(0, 7).map((color, idx) => (
                  <span
                    key={idx}
                    className="h-3.5 w-3.5 rounded-full ring-1 ring-black/40"
                    style={{ backgroundColor: color }}
                    aria-hidden="true"
                  />
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
