// Targeted browser regression for verification tools, without the Rust service fixture.
import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({ ...base, webServer: undefined,
  testMatch: "native-autostart.spec.ts", reporter: [["list"]] });
