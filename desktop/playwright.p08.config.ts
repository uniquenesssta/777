import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/ui",
  testMatch: "host-integration.spec.ts",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:29346",
    viewport: { width: 1440, height: 884 },
    screenshot: "only-on-failure",
    channel: process.platform === "win32" ? "msedge" : undefined,
  },
  webServer: {
    command: "npm run dev:web",
    url: "http://127.0.0.1:29346",
    reuseExistingServer: false,
  },
});
