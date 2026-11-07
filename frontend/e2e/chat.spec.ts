import { expect, test } from "@playwright/test";

// A conversation: what you type lands, the plan shows, the reply follows, a vote goes out.

test.describe("chat", () => {
  test("a turn: message, the reply being written, then the plan and the reply", async ({ page }) => {
    await page.goto("/chat/web");
    await page.getByRole("textbox", { name: "Message" }).fill("coffee 85");
    await page.keyboard.press("Enter");
    await expect(page.getByText("coffee 85").first()).toBeVisible();
    // the stream: pieces of the reply appear before the reply itself lands
    const live = page.locator("[data-kind=stream]");
    await expect(live).toBeVisible();
    await expect(live).toContainText("Noted");
    await expect(page.getByText("Planned", { exact: true })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Noted: “coffee 85”/)).toBeVisible();
    await expect(live).toHaveCount(0); // replaced by the reply, not shown twice
    await page.getByRole("button", { name: "Good answer" }).first().click();
    await expect(page.getByRole("button", { name: "Good answer" }).first()).toHaveAttribute("aria-pressed", "true");
  });

  test("a reply is markdown: a list with bold names, written as a list while it streams", async ({ page }) => {
    await page.goto("/chat/web");
    await page.getByRole("textbox", { name: "Message" }).fill("what is running?");
    await page.keyboard.press("Enter");
    const live = page.locator("[data-kind=stream]");
    await expect(live.locator("strong").first()).toBeVisible();
    const reply = page.locator("[data-kind=assistant]").last();
    await expect(reply.getByRole("listitem")).toHaveCount(3, { timeout: 10_000 });
    await expect(reply.locator("strong", { hasText: "hello" })).toBeVisible();
    await expect(reply).not.toContainText("**");
  });

  test("a module being built shows its progress in the thread: rounds, steps, then the end", async ({ page }) => {
    await page.goto("/chat/web");
    await page.getByRole("textbox", { name: "Message" }).fill("I want to track my water");
    await page.keyboard.press("Enter");
    const offer = page.locator("[data-kind=ask]").last();
    await expect(offer).toContainText("A new module, water");
    await offer.getByRole("button", { name: "Build it" }).click();
    const card = page.locator("[data-kind=progress]");
    await expect(card).toHaveCount(1);
    await expect(card.locator("li[data-state=active]")).toContainText("Round 1 of 6");
    await expect(card.locator("li[data-state=failed]")).toContainText("tests failed: 1 failed, 4 passed", { timeout: 10_000 });
    await expect(card).toHaveAttribute("data-state", "done", { timeout: 10_000 });
    await expect(card).toContainText("Built water v0.1.0");
    await expect(card.locator("li[data-state=done]")).toHaveCount(3);
    await expect(card).toHaveCount(1); // the same card all along
    await expect(page.getByText("water is built and running (version 0.1.0).")).toBeVisible();
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

  test("a question about spending is answered with the module's data: stats, a chart and a table", async ({ page, isMobile }) => {
    await page.goto("/chat/spend-e2e");
    await page.getByRole("textbox", { name: "Message" }).fill("how much did I spend this week?");
    await page.keyboard.press("Enter");
    await expect(page.getByText("Food was most of it this week")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("[data-kind=block-stats]")).toContainText("NT$3,420");
    const bars = page.getByRole("list", { name: "By category" });
    await expect(bars.getByRole("listitem").first()).toHaveText("foodNT$1,820");
    // the chart as a table (on a phone, a card per row), then the entries sorted by amount
    const chart = page.locator("[data-kind=block-chart]");
    await chart.getByRole("button", { name: "Table" }).click();
    const entries = page.locator("[data-kind=block-table]");
    if (isMobile) {
      await expect(chart.getByRole("listitem").first()).toHaveText("foodNT$1,820");
      await expect(entries.getByRole("listitem").first()).toContainText("dinnerNT$350");
    } else {
      await expect(chart.getByRole("table", { name: "By category" })).toContainText("NT$1,820");
      await entries.getByRole("button", { name: "Amount" }).click();
      await expect(entries.getByRole("row").nth(1)).toContainText("taxi");
    }
  });

  test("a question about water gets a meter and a chart you can read with the keyboard", async ({ page }) => {
    await page.goto("/chat/water-e2e");
    await page.getByRole("textbox", { name: "Message" }).fill("water today?");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("meter", { name: "Water today" })).toHaveAttribute("aria-valuetext", "1,500 ml of 2,000 ml, 75%", { timeout: 10_000 });
    const chart = page.getByRole("img", { name: /Water, last 7 days: area chart by Day/ });
    await chart.focus();
    await page.keyboard.press("Home");
    await expect(page.locator("[data-kind=chart-tip]")).toContainText("1,800 ml");
  });
});
