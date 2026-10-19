import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

const letter = path.resolve("../eval/docs/tax_notice_01.pdf");

async function expectNoSeriousA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

test("upload, review, highlight, calendar and print", async ({ page }) => {
  const cspViolations: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (/Content Security Policy|Refused to/i.test(message.text()))
      cspViolations.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your letters" })).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  // First-run privacy notice, then the upload control.
  await page.getByRole("button", { name: "Got it" }).click();
  await page.getByLabel("Choose a PDF, or drop it here").setInputFiles(letter);

  await expect(page).toHaveURL(/\/documents\//);
  await expect(page.getByRole("heading", { name: "Do this" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("You owe")).toBeVisible();
  await expect(page.getByText(/items? needs? your review/)).toBeVisible();

  // The PDF renders under the release CSP: the canvas has non-white pixels.
  const canvas = page.locator("canvas.page__canvas").first();
  await expect(canvas).toBeVisible();
  await expect
    .poll(async () =>
      canvas.evaluate((element) => {
        const c = element as HTMLCanvasElement;
        const data = c.getContext("2d")?.getImageData(0, 0, c.width, c.height).data ?? [];
        // Opaque and dark: text was drawn (a blank canvas is transparent black).
        for (let i = 0; i < data.length; i += 4) {
          if ((data[i + 3] ?? 0) > 200 && (data[i] ?? 255) < 100) return true;
        }
        return false;
      }),
    )
    .toBe(true);

  // Clicking an item's source highlights its passage.
  await page
    .getByRole("button", { name: /Show on page 1/ })
    .first()
    .click();
  await expect(page.locator(".highlight--active").first()).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  // Review: accept the first item.
  const firstItem = page.locator(".item").first();
  await firstItem.getByRole("button", { name: "Accept" }).click();
  await expect(firstItem.getByText("Accepted")).toBeVisible();

  // Calendar download.
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download deadlines (.ics)" }).click();
  const download = await downloadPromise;
  const ics = readFileSync((await download.path())!, "utf-8");
  expect(ics).toContain("BEGIN:VEVENT");
  expect(ics).toContain("TRIGGER:-P7D");

  // Printable plan renders every group.
  await page.getByRole("link", { name: "Printable action plan" }).click();
  await expect(page.getByRole("heading", { name: /Action plan/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Deadlines" })).toBeVisible();
  await expect(page.getByText(/Not legal, medical or financial advice/)).toBeVisible();

  // A refreshed app route still loads (index.html fallback).
  await page.reload();
  await expect(page.getByRole("heading", { name: /Action plan/ })).toBeVisible();

  expect(cspViolations).toEqual([]);
  expect(pageErrors).toEqual([]);
});
