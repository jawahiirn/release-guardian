import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
    testDir: "./tests/e2e",
  timeout: 15_000,
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5177",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
});
