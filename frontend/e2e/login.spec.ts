import { expect, test } from "@playwright/test";

// The token. The mock gateway locks itself when the browser carries the flag (lib/api/client.ts), and
// accepts "mycelium".

test.describe("login", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("mycelium.mock.locked", "1"));
  });

  test("a locked gateway sends the app to /login, refuses a wrong token, opens on the right one", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
    const token = page.getByRole("textbox", { name: "Token" });
    await token.fill("wrong");
    await page.getByRole("button", { name: "Open" }).click();
    // scoped to the form: Next's route announcer is an alert too
    await expect(page.getByRole("form", { name: "Token" }).getByRole("alert")).toHaveText("That is not the gateway's token.");
    await token.fill("mycelium");
    await page.getByRole("button", { name: "Open" }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(/Hansen/);
    expect(await page.evaluate(() => window.localStorage.getItem("mycelium.token"))).toBe("mycelium");
  });
});
