import { describe, expect, it } from "vitest";
import { daysUntil, formatDate, isPassed, localToday, relativeLabel } from "../../src/lib/dates";
import { buildChecklist, undatedDeadlines } from "../../src/lib/grouping";
import { formatCents, roleLabel } from "../../src/lib/money";
import { rectToCss } from "../../src/lib/scale";
import { parseRoute } from "../../src/router";
import { makeItem } from "./fixtures";

describe("rect scaling", () => {
  it("maps PDF points to CSS pixels by rendered width", () => {
    const box = rectToCss({ x0: 72, top: 100, x1: 300, bottom: 112 }, 612, 306);
    expect(box).toEqual({ left: 36, top: 50, width: 114, height: 6 });
  });
});

describe("display-time dates", () => {
  it("counts days in the viewer's calendar, never stored", () => {
    expect(daysUntil("2026-12-02", "2026-11-30")).toBe(2);
    expect(isPassed("2026-10-14", "2026-10-19")).toBe(true);
    expect(relativeLabel("2026-10-14", "2026-10-19")).toMatch(/passed/);
    expect(relativeLabel("2026-10-20", "2026-10-19")).toBe("Due tomorrow");
    expect(formatDate("2027-01-01")).toBe("January 1, 2027");
    expect(localToday(new Date(2026, 0, 5))).toBe("2026-01-05");
  });

  it("is not thrown off by daylight-saving changes", () => {
    expect(daysUntil("2026-11-02", "2026-10-31")).toBe(2);
    expect(daysUntil("2026-03-09", "2026-03-07")).toBe(2);
  });
});

describe("money", () => {
  it("formats cents and role labels", () => {
    expect(formatCents(124000)).toBe("$1,240.00");
    expect(roleLabel("balance")).toBe("Balance — not a bill");
    expect(roleLabel(null)).toBe("Amount");
  });
});

describe("checklist grouping", () => {
  it("puts each item in its group, in the plan's order", () => {
    const pay = makeItem({ kind: "action", text: "Pay" });
    const due = makeItem({ kind: "deadline", parent_item_id: pay.id, due_date: "2026-12-02" });
    const send = makeItem({ kind: "document" });
    const later = makeItem({ kind: "deadline", due_date: "2027-01-01" });
    const owed = makeItem({ kind: "amount", amount_cents: 100 });
    const maybe = makeItem({
      kind: "action",
      requirement: "conditional",
      condition: "If you disagree",
    });
    const phone = makeItem({ kind: "contact" });
    const rejected = makeItem({ status: "rejected" });
    const dismissed = makeItem({ review_state: "dismissed" });

    const checklist = buildChecklist([
      phone,
      maybe,
      owed,
      later,
      send,
      due,
      pay,
      rejected,
      dismissed,
    ]);
    expect(checklist.groups.map((g) => g.id)).toEqual([
      "do",
      "send",
      "dates",
      "amounts",
      "conditional",
      "contacts",
    ]);
    expect(checklist.groups[0]?.items).toEqual([pay]);
    expect(checklist.groups[2]?.items).toEqual([later]); // the attached deadline isn't listed twice
    expect(checklist.deadlineFor.get(pay.id)).toBe(due);
    expect(checklist.rejected).toEqual([rejected]);
    expect(checklist.dismissed).toEqual([dismissed]);
  });

  it("orders by due date, then by position in the letter", () => {
    const undated = makeItem({ kind: "deadline", position: 1 });
    const late = makeItem({ kind: "deadline", due_date: "2027-02-01", position: 2 });
    const soon = makeItem({ kind: "deadline", due_date: "2026-11-01", position: 3 });
    const [dates] = buildChecklist([undated, late, soon]).groups;
    expect(dates?.items.map((i) => i.id)).toEqual([soon.id, late.id, undated.id]);
  });

  it("filters to items that need review", () => {
    const ok = makeItem();
    const check = makeItem({
      status: "needs_review",
      reasons: ["Quote only approximately matches"],
    });
    const all = buildChecklist([ok, check]);
    expect(all.needsReview).toBe(1);
    const only = buildChecklist([ok, check], { onlyNeedsReview: true });
    expect(only.groups.flatMap((g) => g.items)).toEqual([check]);
  });

  it("lists deadlines without a date for the print page", () => {
    const undated = makeItem({ kind: "deadline", due_date: null });
    expect(
      undatedDeadlines([undated, makeItem({ kind: "deadline", due_date: "2026-12-01" })]),
    ).toEqual([undated]);
  });
});

describe("routes", () => {
  it("parses app routes", () => {
    expect(parseRoute("/")).toEqual({ name: "home" });
    expect(parseRoute("/documents/abc")).toEqual({ name: "document", id: "abc" });
    expect(parseRoute("/documents/abc/print")).toEqual({ name: "print", id: "abc" });
    expect(parseRoute("/nope")).toEqual({ name: "not_found" });
  });
});
