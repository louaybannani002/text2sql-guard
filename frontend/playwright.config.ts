/**
 * End-to-end tests against the running docker compose stack (`make e2e`, or `make up` then
 * `pnpm e2e`). They use the real API, database, cache and LLM; nothing is mocked.
 */
import { defineConfig, devices } from "@playwright/test";

const channel = process.env.PLAYWRIGHT_CHANNEL ?? "chrome"; // "chromium": run `playwright install chromium`

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  // One shared demo user and real rate limits: run serially.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 120_000, // a fresh question waits for the LLM
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    // 127.0.0.1, not localhost: on Windows Node tries ::1 first, and the ports are IPv4-only.
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel } },
  ],
});
