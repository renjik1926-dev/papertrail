import type { Item, ItemsPayload, ReviewIn } from "../api/client";
import { buildChecklist } from "../lib/grouping";
import { ItemCard } from "./ItemCard";

interface Props {
  payload: ItemsPayload;
  today: string;
  activeItemId: string | null;
  onlyNeedsReview: boolean;
  onToggleFilter: () => void;
  onShow: (itemId: string) => void;
  onReview: (itemId: string, body: ReviewIn) => Promise<void>;
}

export function Checklist({
  payload,
  today,
  activeItemId,
  onlyNeedsReview,
  onToggleFilter,
  onShow,
  onReview,
}: Props) {
  const all = buildChecklist(payload.items);
  const checklist = onlyNeedsReview
    ? buildChecklist(payload.items, { onlyNeedsReview: true })
    : all;
  const card = (item: Item) => (
    <ItemCard
      key={item.id}
      item={item}
      deadline={checklist.deadlineFor.get(item.id)}
      today={today}
      active={item.id === activeItemId}
      onShow={onShow}
      onReview={onReview}
    />
  );

  if (payload.items.length === 0) {
    return (
      <p className="empty">
        No actions, deadlines, amounts or contacts were found in this letter. Read it yourself to be
        sure nothing is needed.
      </p>
    );
  }

  return (
    <div className="checklist">
      {all.needsReview > 0 && (
        <p className="summary">
          <button
            type="button"
            className="link-button"
            aria-pressed={onlyNeedsReview}
            onClick={onToggleFilter}
          >
            {onlyNeedsReview
              ? "Show all items"
              : `${all.needsReview} ${all.needsReview === 1 ? "item needs" : "items need"} your review`}
          </button>
        </p>
      )}
      {payload.notes.length > 0 && (
        <div className="notes">
          <h2 className="group__title">Notes</h2>
          <ul>
            {payload.notes.map((note) => (
              <li key={note.id}>{note.text}</li>
            ))}
          </ul>
        </div>
      )}
      {checklist.groups.map((group) => (
        <section className="group" key={group.id} aria-labelledby={`group-${group.id}`}>
          <h2 className="group__title" id={`group-${group.id}`}>
            {group.title}
          </h2>
          <ul className="items">{group.items.map(card)}</ul>
        </section>
      ))}
      {payload.no_longer_found.length > 0 && (
        <div className="notes">
          <h2 className="group__title">No longer found</h2>
          <p>These items you reviewed earlier weren't found when the letter was processed again:</p>
          <ul>
            {payload.no_longer_found.map((lost) => (
              <li key={lost.id}>{lost.text}</li>
            ))}
          </ul>
        </div>
      )}
      {checklist.dismissed.length > 0 && (
        <details className="collapsed">
          <summary>Dismissed ({checklist.dismissed.length})</summary>
          <ul className="items">{checklist.dismissed.map(card)}</ul>
        </details>
      )}
      {all.rejected.length > 0 && (
        <details className="collapsed">
          <summary>
            Left out because they couldn't be found in the letter ({all.rejected.length})
          </summary>
          <p className="hint">
            The AI model suggested these, but code couldn't match them to the letter, so they aren't
            on your checklist.
          </p>
          <ul className="items">
            {all.rejected.map((item) => (
              <ItemCard
                key={item.id}
                item={item}
                deadline={undefined}
                today={today}
                active={false}
                readOnly
                onShow={onShow}
                onReview={onReview}
              />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
