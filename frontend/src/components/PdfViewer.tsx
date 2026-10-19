// Renders each page to a canvas sized to the panel, with a highlight layer on top.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
// The legacy build includes polyfills: the modern build of pdf.js 6 needs very recent
// browsers (it calls Map.getOrInsertComputed, which Chromium 141 and Safari lack).
import * as pdfjs from "pdfjs-dist/legacy/build/pdf.mjs";
import type { PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";
import type { Item } from "../api/client";
import { HighlightLayer } from "./HighlightLayer";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/legacy/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/**
 * Loading options. `isEvalSupported: false` is the documented workaround for CVE-2024-4367.
 * pdf.js removed that eval code path in 5.7.284, so on the version pinned here the flag is a
 * no-op; it stays so the viewer remains safe if anyone pins an older pdfjs-dist (>= 4.2.67).
 */
export function loadingParams(url: string) {
  const params = { url, isEvalSupported: false, enableXfa: false };
  return params;
}

interface PageSize {
  width: number;
  height: number;
}

interface Props {
  url: string;
  pages: PageSize[];
  items: Item[];
  activeItemId: string | null;
  onSelect: (itemId: string) => void;
}

export function PdfViewer({ url, pages, items, activeItemId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const task = pdfjs.getDocument(loadingParams(url));
    task.promise.then(
      (loaded) => {
        if (!cancelled) setDoc(loaded);
      },
      () => {
        if (!cancelled) setError("The PDF couldn't be shown.");
      },
    );
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0]?.contentRect.width ?? 0);
      setWidth((current) => (Math.abs(current - next) > 4 ? next : current));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const rectsByPage = useMemo(() => {
    const map = new Map<number, { item: Item; rectIndex: number }[]>();
    for (const item of items) {
      item.rects.forEach((rect, rectIndex) => {
        const list = map.get(rect.page_no) ?? [];
        list.push({ item, rectIndex });
        map.set(rect.page_no, list);
      });
    }
    return map;
  }, [items]);

  useEffect(() => {
    if (!activeItemId || !container.current) return;
    const target = container.current.querySelector(`[data-item="${CSS.escape(activeItemId)}"]`);
    if (target) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    }
  }, [activeItemId, width, doc]);

  return (
    <div className="viewer" ref={container}>
      {error && <p className="notice notice--error">{error}</p>}
      {pages.map((size, index) => (
        <figure className="page" key={index}>
          <figcaption className="page__label">
            Page {index + 1} of {pages.length}
          </figcaption>
          <PageCanvas doc={doc} pageNo={index + 1} size={size} width={width}>
            <HighlightLayer
              entries={rectsByPage.get(index + 1) ?? []}
              pageWidth={size.width}
              renderedWidth={width}
              activeItemId={activeItemId}
              onSelect={onSelect}
            />
          </PageCanvas>
        </figure>
      ))}
    </div>
  );
}

function PageCanvas({
  doc,
  pageNo,
  size,
  width,
  children,
}: {
  doc: PDFDocumentProxy | null;
  pageNo: number;
  size: PageSize;
  width: number;
  children: ReactNode;
}) {
  const holder = useRef<HTMLDivElement>(null);
  const height = width ? (size.height * width) / size.width : 0;

  useEffect(() => {
    if (!doc || !width) return;
    let cancelled = false;
    let task: { cancel: () => void; promise: Promise<void> } | null = null;
    // Each render draws into its own canvas, swapped in only when finished, so a resize
    // never collides with a render that is still being cancelled.
    const canvas = document.createElement("canvas");
    canvas.className = "page__canvas";
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    void doc.getPage(pageNo).then((page) => {
      if (cancelled) return;
      const base = page.getViewport({ scale: 1 });
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: (width / base.width) * ratio });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      task = page.render({ canvas, viewport });
      task.promise.then(
        () => {
          if (!cancelled) holder.current?.replaceChildren(canvas);
        },
        () => undefined, // cancelled by a newer render
      );
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, pageNo, width, height]);

  return (
    <div className="page__surface" style={{ width, height }}>
      <div ref={holder} className="page__holder" />
      {children}
    </div>
  );
}
