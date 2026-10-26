import { expect, test } from "@playwright/test";

// The home page against the mock bus: the greeting, the question that needs you, the live timeline.

test.describe("home", () => {
  test("greets, lists today, and shows the modules that are alive", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Good \w+, Hansen/);
    const timeline = page.getByRole("list", { name: "Timeline" });
    await expect(timeline.getByText("You said “dinner with Mei at 7, remind me at 6”")).toBeVisible();
    await expect(page.getByRole("link", { name: /hello/ }).first()).toBeVisible();
    await expect(page.getByTitle("telegram", { exact: true })).toHaveText("Chat");
  });

  test("a question Main asked can be answered from the card, and the answer lands on the bus", async ({ page }) => {
    await page.goto("/");
    const needs = page.getByRole("region", { name: "Needs you" });
    await expect(needs.getByText("Should I keep the Friday reminder for the garden watering?")).toBeVisible();
    await needs.getByRole("button", { name: "Keep it" }).click();
    await expect(needs.getByText("Should I keep the Friday reminder")).toHaveCount(0);
    await expect(page.getByRole("list", { name: "Timeline" }).getByText("You answered “Keep it”")).toBeVisible();
  });

  test("raw bus shows the subjects", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "raw bus" }).click();
    await expect(page.getByRole("list", { name: "Timeline" }).getByText("out.ask", { exact: true })).toBeVisible();
  });

  test("a prompt sends a message and opens the thread", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "What is running right now?" }).click();
    await expect(page).toHaveURL(/\/chat\/web$/);
    await expect(page.locator("[data-kind=user]")).toHaveText("What is running right now?");
    await expect(page.getByText(/hello is running/)).toBeVisible({ timeout: 10_000 });
  });
});
