// Absolutely positioned highlight boxes for one page. aria-hidden: the checklist is the
// accessible representation (BUILD_PLAN §10).
import type { Item } from "../api/client";
import { rectToCss } from "../lib/scale";

interface Props {
  entries: { item: Item; rectIndex: number }[];
  pageWidth: number;
  renderedWidth: number;
  activeItemId: string | null;
  onSelect: (itemId: string) => void;
}

export function HighlightLayer({
  entries,
  pageWidth,
  renderedWidth,
  activeItemId,
  onSelect,
}: Props) {
  if (!renderedWidth) return null;
  return (
    <div className="highlights" aria-hidden="true">
      {entries.map(({ item, rectIndex }) => {
        const rect = item.rects[rectIndex];
        if (!rect) return null;
        const box = rectToCss(rect, pageWidth, renderedWidth);
        const active = item.id === activeItemId;
        return (
          <div
            key={`${item.id}-${rectIndex}`}
            data-item={rectIndex === 0 ? item.id : undefined}
            className={`highlight${active ? " highlight--active" : ""}${
              item.status === "needs_review" ? " highlight--review" : ""
            }`}
            style={{ left: box.left, top: box.top, width: box.width, height: box.height }}
            title={item.text}
            onClick={() => onSelect(item.id)}
          />
        );
      })}
    </div>
  );
}
