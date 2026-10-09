/**
 * #253 Chart export as PNG or SVG.
 *
 * Serializes an in-DOM SVG element into a clean standalone vector SVG file
 * or renders it into an offscreen high-DPI HTML5 canvas for PNG download.
 */

export interface ExportChartOptions {
  backgroundColor?: string;
  scale?: number;
}

export function exportSvgElement(
  svgEl: SVGSVGElement,
  filename: string,
  format: "svg" | "png",
  options?: ExportChartOptions
): Promise<void> {
  const bg = options?.backgroundColor ?? "#090a0f";
  const scale = options?.scale ?? 2;

  const clone = svgEl.cloneNode(true) as SVGSVGElement;
  if (!clone.getAttribute("xmlns")) {
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  }

  const viewBox = clone.viewBox?.baseVal;
  const width = viewBox?.width || svgEl.clientWidth || 600;
  const height = viewBox?.height || svgEl.clientHeight || 300;
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  const svgXml = new XMLSerializer().serializeToString(clone);

  if (format === "svg") {
    const blob = new Blob([svgXml], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    triggerDownload(url, `${filename}.svg`);
    setTimeout(() => URL.revokeObjectURL(url), 100);
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const img = new Image();
    const svgBlob = new Blob([svgXml], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);

    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = width * scale;
        canvas.height = height * scale;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          URL.revokeObjectURL(url);
          resolve();
          return;
        }

        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        canvas.toBlob((blob) => {
          URL.revokeObjectURL(url);
          if (blob) {
            const pngUrl = URL.createObjectURL(blob);
            triggerDownload(pngUrl, `${filename}.png`);
            setTimeout(() => URL.revokeObjectURL(pngUrl), 100);
          }
          resolve();
        }, "image/png");
      } catch (err) {
        URL.revokeObjectURL(url);
        reject(err);
      }
    };

    img.onerror = (e) => {
      URL.revokeObjectURL(url);
      reject(e);
    };

    img.src = url;
  });
}

function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
