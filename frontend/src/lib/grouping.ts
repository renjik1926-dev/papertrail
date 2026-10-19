// Checklist groups, in this order (BUILD_PLAN §10). Each item appears once, in its own group.
import type { Item } from "../api/client";

export type GroupId = "do" | "send" | "dates" | "amounts" | "conditional" | "contacts";

export interface Group {
  id: GroupId;
  title: string;
  items: Item[];
}

export const GROUP_TITLES: Record<GroupId, string> = {
  do: "Do this",
  send: "Send these",
  dates: "Key dates",
  amounts: "Amounts",
  conditional: "Only if it applies to you",
  contacts: "Contacts",
};

const ORDER: GroupId[] = ["do", "send", "dates", "amounts", "conditional", "contacts"];

export function isConditional(item: Item): boolean {
  return item.requirement === "conditional" || item.requirement === "optional";
}

export function groupOf(item: Item, attachedDeadlines: Set<string>): GroupId | null {
  switch (item.kind) {
    case "action":
      return isConditional(item) ? "conditional" : "do";
    case "document":
      return isConditional(item) ? "conditional" : "send";
    case "deadline":
      if (attachedDeadlines.has(item.id)) return null; // shown as a badge on its action
      return isConditional(item) ? "conditional" : "dates";
    case "amount":
      return "amounts";
    case "contact":
      return "contacts";
    default:
      return null;
  }
}

/** The date an item is due: its own, or its attached deadline's. */
export function dueDateOf(item: Item, deadlineFor: Map<string, Item>): string | null {
  return item.due_date ?? deadlineFor.get(item.id)?.due_date ?? null;
}

/** By due date (soonest first, undated last), then by position in the letter. */
export function compareItems(a: Item, b: Item, deadlineFor: Map<string, Item>): number {
  const da = dueDateOf(a, deadlineFor);
  const db = dueDateOf(b, deadlineFor);
  if (da && db && da !== db) return da < db ? -1 : 1;
  if (da && !db) return -1;
  if (!da && db) return 1;
  return a.position - b.position;
}

export interface Checklist {
  groups: Group[];
  dismissed: Item[];
  rejected: Item[];
  needsReview: number;
  deadlineFor: Map<string, Item>;
}

export function buildChecklist(
  items: Item[],
  options: { onlyNeedsReview?: boolean } = {},
): Checklist {
  const shown = items.filter((i) => i.status !== "rejected");
  const rejected = items.filter((i) => i.status === "rejected");
  const live = shown.filter((i) => i.review_state !== "dismissed");
  const dismissed = shown.filter((i) => i.review_state === "dismissed");

  const deadlineFor = new Map<string, Item>();
  const attached = new Set<string>();
  const liveIds = new Set(live.map((i) => i.id));
  for (const item of live) {
    if (item.kind === "deadline" && item.parent_item_id && liveIds.has(item.parent_item_id)) {
      deadlineFor.set(item.parent_item_id, item);
      attached.add(item.id);
    }
  }

  const needsReviewIds = new Set(
    live
      .filter(
        (i) => i.status === "needs_review" || deadlineFor.get(i.id)?.status === "needs_review",
      )
      .filter((i) => !attached.has(i.id))
      .map((i) => i.id),
  );

  const buckets = new Map<GroupId, Item[]>(ORDER.map((id) => [id, []]));
  for (const item of live) {
    const group = groupOf(item, attached);
    if (!group) continue;
    if (options.onlyNeedsReview && !needsReviewIds.has(item.id)) continue;
    buckets.get(group)?.push(item);
  }
  const groups = ORDER.map((id) => ({
    id,
    title: GROUP_TITLES[id],
    items: (buckets.get(id) ?? []).sort((a, b) => compareItems(a, b, deadlineFor)),
  })).filter((g) => g.items.length > 0);

  return { groups, dismissed, rejected, needsReview: needsReviewIds.size, deadlineFor };
}

/** Deadlines that can't go in a calendar (no resolvable date): the print page lists these. */
export function undatedDeadlines(items: Item[]): Item[] {
  return items.filter(
    (i) =>
      i.kind === "deadline" &&
      i.status !== "rejected" &&
      i.review_state !== "dismissed" &&
      !i.due_date,
  );
}
