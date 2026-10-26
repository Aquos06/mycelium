import { expect, test } from "@playwright/test";

// A conversation: what you type lands, the plan shows, the reply follows, a vote goes out.

test.describe("chat", () => {
  test("a turn: message, plan, reply", async ({ page }) => {
    await page.goto("/chat/web");
    await page.getByRole("textbox", { name: "Message" }).fill("coffee 85");
    await page.keyboard.press("Enter");
    await expect(page.getByText("coffee 85").first()).toBeVisible();
    await expect(page.getByText("Planned", { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Noted: “coffee 85”/)).toBeVisible();
    await page.getByRole("button", { name: "Good answer" }).first().click();
    await expect(page.getByRole("button", { name: "Good answer" }).first()).toHaveAttribute("aria-pressed", "true");
  });

  test("new chat starts a fresh thread and the rail remembers the old one", async ({ page }, info) => {
    test.skip(info.project.name === "mobile", "the rail with recent chats exists at md and up");
    await page.goto("/chat/web");
    await page.getByRole("textbox", { name: "Message" }).fill("remember the dentist on Monday");
    await page.keyboard.press("Enter");
    await expect(page.getByText("remember the dentist on Monday").first()).toBeVisible();
    await page.getByRole("button", { name: "New chat" }).click();
    await expect(page).toHaveURL(/\/chat\/web-/);
    await expect(page.getByText("Say something. Main recalls")).toBeVisible();
    await expect(page.getByRole("link", { name: "remember the dentist on Monday" })).toBeVisible();
  });

  test("/chat opens the default thread", async ({ page }) => {
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/chat\/web$/);
  });
});
