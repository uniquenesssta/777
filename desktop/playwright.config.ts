import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "tests/ui",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:29346",
    viewport: { width: 1440, height: 884 },
    screenshot: "only-on-failure",
    channel: process.platform === "win32" ? "msedge" : undefined,
    launchOptions: process.env.P07_BROWSER_PATH
      ? {
          executablePath: process.env.P07_BROWSER_PATH,
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        }
      : {},
  },
  reporter: [["list"], ["json", { outputFile: "test-results/report.json" }]],
  webServer: [
    {
      command: "npm run dev:web",
      url: "http://127.0.0.1:29346",
      reuseExistingServer: false,
    },
    {
      command: "python ../tools/p07_desktop_fixture.py --port 18777",
      url: "http://127.0.0.1:18777/health",
      reuseExistingServer: false,
      timeout: 60000,
    },
  ],
});
