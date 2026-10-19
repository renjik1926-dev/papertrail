// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ItemCard } from "../../src/components/ItemCard";
import { makeItem } from "./fixtures";

vi.mock("pdfjs-dist/legacy/build/pdf.mjs", () => ({
  GlobalWorkerOptions: {},
  getDocument: vi.fn(),
}));

afterEach(cleanup);

const noop = async () => undefined;

describe("ItemCard", () => {
  it("shows status as text, not colour alone, and the quote as plain text", () => {
    const item = makeItem({ quote: "<img src=x onerror=alert(1)> Pay now." });
    render(
      <ItemCard
        item={item}
        deadline={undefined}
        today="2026-10-19"
        active={false}
        onShow={() => {}}
        onReview={noop}
      />,
    );
    expect(screen.getByText(/Verified against the letter/)).toBeTruthy();
    expect(screen.getByText("<img src=x onerror=alert(1)> Pay now.")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("shows reasons and the attached deadline for items that need review", () => {
    const action = makeItem({ text: "Pay the bill" });
    const deadline = makeItem({
      kind: "deadline",
      due_date: "2026-10-14",
      status: "needs_review",
      reasons: ["The letter says no action/payment may be needed"],
    });
    render(
      <ItemCard
        item={action}
        deadline={deadline}
        today="2026-10-19"
        active={false}
        onShow={() => {}}
        onReview={noop}
      />,
    );
    expect(screen.getByText(/Needs review/)).toBeTruthy();
    expect(screen.getByText(/no action\/payment may be needed/)).toBeTruthy();
    expect(screen.getByText(/This date has passed/)).toBeTruthy();
  });

  it("sends review actions and labels edited items", async () => {
    const onReview = vi.fn(noop);
    const item = makeItem({
      review_state: "edited",
      original: {
        text: "Old",
        due_date: null,
        amount_cents: null,
        requirement: "required",
        condition: "",
      },
    });
    render(
      <ItemCard
        item={item}
        deadline={undefined}
        today="2026-10-19"
        active={false}
        onShow={() => {}}
        onReview={onReview}
      />,
    );
    expect(screen.getByText("Edited by you")).toBeTruthy();
    expect(screen.getByText(/first read this as: “Old”/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onReview).toHaveBeenCalledWith(item.id, { action: "dismiss" });
  });

  it("calls onShow with the item when the source chip is clicked", () => {
    const onShow = vi.fn();
    const item = makeItem({ page_no: 2 });
    render(
      <ItemCard
        item={item}
        deadline={undefined}
        today="2026-10-19"
        active={false}
        onShow={onShow}
        onReview={noop}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show on page 2" }));
    expect(onShow).toHaveBeenCalledWith(item.id);
  });
});

describe("pdf.js loading options", () => {
  it("disables eval (CVE-2024-4367 workaround) and XFA", async () => {
    const { loadingParams } = await import("../../src/components/PdfViewer");
    expect(loadingParams("/api/documents/x/file")).toEqual({
      url: "/api/documents/x/file",
      isEvalSupported: false,
      enableXfa: false,
    });
  });
});
