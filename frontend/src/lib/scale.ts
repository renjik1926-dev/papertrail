// A rect in PDF points maps to CSS pixels with scale = renderedPageWidthPx / page.width
// (BUILD_PLAN §10).

export interface PdfRect {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
}

export interface CssBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function rectToCss(rect: PdfRect, pageWidthPt: number, renderedWidthPx: number): CssBox {
  const scale = renderedWidthPx / pageWidthPt;
  return {
    left: rect.x0 * scale,
    top: rect.top * scale,
    width: (rect.x1 - rect.x0) * scale,
    height: (rect.bottom - rect.top) * scale,
  };
}
