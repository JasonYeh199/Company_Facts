import { expect, test } from "@playwright/test";

test("searches a SEC company and exposes support status", async ({ page }) => {
  await page.route("**/api/v1/companies/search**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        {
          cik: "0000320193",
          name: "Apple Inc.",
          supported: true,
          accounting_standard: "us-gaap",
          tickers: [{ ticker: "AAPL", exchange: "Nasdaq", is_active: true }],
        },
      ]),
    });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /從一筆數字/ })).toBeVisible();
  await page.getByLabel("搜尋公司").fill("AAPL");
  await expect(page.getByText("Apple Inc.")).toBeVisible();
  await expect(page.getByText("US-GAAP", { exact: true })).toBeVisible();
});
