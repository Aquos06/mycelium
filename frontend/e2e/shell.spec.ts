import { expect, test } from "@playwright/test";

// The shell at two widths: the rail on a desktop, the tab bar on a phone; the voice shortcut; the 404.

test.describe("shell", () => {
  test("the right navigation for the width", async ({ page }, info) => {
    await page.goto("/");
    const rail = page.getByRole("complementary").filter({ hasText: "Recent chats" });
    const tabs = page.getByRole("navigation", { name: "Main" });
    if (info.project.name === "mobile") {
      await expect(rail).toBeHidden();
      await expect(tabs.getByRole("link", { name: "Modules" })).toBeVisible();
      await tabs.getByRole("link", { name: "Modules" }).click();
      await expect(page).toHaveURL(/\/modules$/);
    } else {
      await expect(rail).toBeVisible();
      await expect(rail.getByText("Live")).toBeVisible();
      await expect(rail.getByRole("link", { name: /hello/ })).toBeVisible();
    }
  });

  test("⌘J opens voice, which says it is not wired, and Esc leaves", async ({ page }, info) => {
    test.skip(info.project.name === "mobile", "no keyboard on a phone");
    await page.goto("/");
    await page.keyboard.press("Meta+j");
    await expect(page).toHaveURL(/\/voice$/);
    await expect(page.getByRole("dialog", { name: "Voice" })).toContainText("Voice is not on the bus yet.");
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/$/);
  });

  test("voice's type-instead goes to the chat", async ({ page }) => {
    await page.goto("/voice");
    await page.getByRole("button", { name: "Type instead" }).click();
    await expect(page).toHaveURL(/\/chat\/web$/);
  });

  test("an unknown path is a 404 that leads home", async ({ page }) => {
    const r = await page.goto("/nothing/here");
    expect(r?.status()).toBe(404);
    await page.getByRole("link", { name: "Back home" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Hansen/);
  });
});
