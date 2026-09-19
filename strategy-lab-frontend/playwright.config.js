import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const macChrome =
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: {
    baseURL: "http://127.0.0.1:3004",
    headless: true,
    launchOptions: {
      executablePath:
        process.env.PLAYWRIGHT_CHROME ||
        (existsSync(macChrome) ? macChrome : undefined),
    },
  },
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 3004",
    url: "http://127.0.0.1:3004",
    reuseExistingServer: false,
  },
});
