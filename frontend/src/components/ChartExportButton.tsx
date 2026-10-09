import { useState, useRef, useEffect } from "react";
import { ExportIcon } from "./Icons";
import { exportSvgElement } from "./chartExport";

interface Props {
  title: string;
  getSvg: () => SVGSVGElement | null;
  className?: string;
}

export default function ChartExportButton({ title, getSvg, className = "" }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", onClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
    };
  }, [open]);

  const handleExport = async (format: "png" | "svg") => {
    const svgEl = getSvg();
    if (!svgEl) return;
    setBusy(true);
    setOpen(false);
    try {
      const sanitized = title.toLowerCase().replace(/[^a-z0-9_-]/g, "_");
      await exportSvgElement(svgEl, sanitized, format);
    } catch {
      // export error handled gracefully
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={menuRef} className={`relative inline-block ${className}`}>
      <button
        onClick={() => setOpen(!open)}
        disabled={busy}
        aria-label={`Export ${title} chart`}
        aria-haspopup="true"
        aria-expanded={open}
        className="flex items-center gap-1 rounded-lg border border-white/[0.04] bg-white/[0.02] px-2 py-1 text-xs text-ink-400 transition-colors hover:bg-white/[0.06] hover:text-ink-200 disabled:opacity-50"
      >
        <ExportIcon className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Export</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-20 mt-1.5 w-32 rounded-xl border border-white/10 bg-zinc-900/95 p-1 text-xs shadow-2xl backdrop-blur"
        >
          <button
            role="menuitem"
            onClick={() => handleExport("png")}
            className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-ink-200 transition-colors hover:bg-white/[0.08] hover:text-white"
          >
            <span>PNG</span>
            <span className="font-mono text-[10px] text-ink-500">2x Retina</span>
          </button>
          <button
            role="menuitem"
            onClick={() => handleExport("svg")}
            className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-ink-200 transition-colors hover:bg-white/[0.08] hover:text-white"
          >
            <span>SVG</span>
            <span className="font-mono text-[10px] text-ink-500">Vector</span>
          </button>
        </div>
      )}
    </div>
  );
}
