import { defineConfig, devices } from "@playwright/test";

// E2E config. Boots a PRODUCTION build of the app in mock mode (NEXT_PUBLIC_MOCK=1), so the UI is driven
// end to end without a gateway or a bus. Port 3131: clear of 3000 (dev) and 8080 (the gateway).
const PORT = Number(process.env.E2E_PORT ?? 3131);
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  timeout: 45_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
  },
  // Two viewports, because the shell genuinely differs: the tab bar exists only below md and the sidebar
  // only at md and up, so no single viewport can test it.
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
  webServer: {
    command: `NEXT_PUBLIC_MOCK=1 pnpm build && NEXT_PUBLIC_MOCK=1 PORT=${PORT} pnpm start`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
