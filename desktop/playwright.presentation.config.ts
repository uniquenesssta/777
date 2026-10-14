import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({...base,testMatch:"presentation.spec.ts",webServer:[base.webServer[0]],reporter:[["list"]]});
