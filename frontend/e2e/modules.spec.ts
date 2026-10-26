import { expect, test } from "@playwright/test";

// Modules: the grown ones with their state, the core services, one module's page and its controls.

test.describe("modules", () => {
  test("lists grown and core, and the filter narrows", async ({ page }) => {
    await page.goto("/modules");
    const grown = page.getByRole("region", { name: "Grown" });
    await expect(grown.getByRole("link", { name: /hello/ })).toContainText("Running");
    await expect(grown.getByRole("link", { name: /budget/ })).toContainText("Growing");
    await expect(grown.getByRole("link", { name: /garden/ })).toContainText("Paused");
    await expect(page.getByRole("region", { name: "Core" }).getByRole("link", { name: /supervisor/ })).toContainText("Running");
    await page.getByRole("tab", { name: "Core" }).click();
    await expect(grown).toHaveCount(0);
  });

  test("a module's page: wiring, ask it directly, logs, pause asks twice", async ({ page }) => {
    await page.goto("/modules/hello");
    await expect(page.getByRole("heading", { level: 1, name: "hello" })).toBeVisible();
    await expect(page.getByLabel("Wiring")).toContainText("mod.hello.message.counted");
    await page.getByRole("button", { name: /Run/ }).click();
    await expect(page.getByTestId("ask-result")).toContainText('"counted": 3');
    await page.getByRole("button", { name: "Logs" }).click();
    await expect(page.getByRole("region", { name: "Logs" })).toContainText("subscribed sense.chat");
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Sure? Pause" })).toBeVisible();
  });

  test("a core service has a page too", async ({ page }) => {
    await page.goto("/modules/gateway");
    await expect(page.getByRole("heading", { level: 1, name: "gateway" })).toBeVisible();
    await expect(page.getByLabel("Properties")).toContainText("rpc.llm.usage");
  });
});
