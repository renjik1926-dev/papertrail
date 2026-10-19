import type { Item } from "../../src/api/client";

let counter = 0;

export function makeItem(overrides: Partial<Item> = {}): Item {
  counter += 1;
  return {
    id: `item-${counter}`,
    kind: "action",
    text: `Item ${counter}`,
    requirement: "required",
    condition: "",
    quote: "You must respond within 60 days.",
    due_date: null,
    due_rule: null,
    due_calc: null,
    amount_cents: null,
    amount_role: null,
    parent_item_id: null,
    status: "verified",
    review_state: "none",
    item_key: `key-${counter}`,
    position: counter * 100,
    page_no: 1,
    sources: [],
    rects: [{ page_no: 1, x0: 72, top: 100, x1: 300, bottom: 112 }],
    checks: [],
    reasons: [],
    original: null,
    ...overrides,
  };
}
