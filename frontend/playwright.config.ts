import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// End-to-end tests run the real backend with the Replay provider (no API key) serving the
// built frontend on the same origin, so the Content-Security-Policy is the release one.
const port = 8765;
const dataDir = path.join(os.tmpdir(), `papertrail-e2e-${process.pid}`);
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], launchOptions: { executablePath } } },
  ],
  webServer: {
    command: `node tests/e2e/serve.mjs ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
    timeout: 120_000,
    env: {
      PAPERTRAIL_PROVIDER: "replay",
      PAPERTRAIL_DATA_DIR: dataDir,
      PAPERTRAIL_RECORDINGS_DIR: path.resolve("../eval/recorded"),
      ANTHROPIC_API_KEY: "",
    },
  },
});
