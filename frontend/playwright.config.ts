import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 300_000,        // 5 min per test — LLM calls are slow
  retries: 0,
  workers: 1,              // sequential — tests share backend state
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
})
