import { expect, test } from "@playwright/test";

// Settings: what the gateway loaded, which keys are set, the app's own tab.

test.describe("settings", () => {
  test("/settings opens on models and shows the slots", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings\/models$/);
    const planner = page.getByRole("region", { name: "Planner" });
    await expect(planner.getByText("claude-sonnet-5-5")).toBeVisible();
    await expect(planner.getByText("active", { exact: true })).toBeVisible();
    await expect(planner.getByText("shadow", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Monthly budget")).toContainText("$4.37");
  });

  test("keys says which are set, never a value", async ({ page }) => {
    await page.goto("/settings/keys");
    await expect(page.locator("[data-key=ANTHROPIC_API_KEY]")).toContainText("set");
    await expect(page.locator("[data-key=OPENAI_API_KEY]")).toContainText("not set");
  });

  test("the tabs navigate and this app's tab reads the gateway", async ({ page }) => {
    await page.goto("/settings/models");
    await page.getByRole("navigation", { name: "Settings" }).getByRole("link", { name: /This app/ }).click();
    await expect(page).toHaveURL(/\/settings\/web$/);
    const main = page.getByRole("main");
    await expect(main.getByText("Hansen", { exact: true })).toBeVisible();
    await expect(main.getByText("open", { exact: true })).toBeVisible();
  });

  test("an unknown tab is a 404", async ({ page }) => {
    const r = await page.goto("/settings/nope");
    expect(r?.status()).toBe(404);
  });
});
