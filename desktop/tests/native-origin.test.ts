import test from "node:test";
import assert from "node:assert/strict";
import { productionOrigin } from "./native-origin.mjs";

test("actual Windows Tauri production origins accept embedded-page paths", () => {
  assert.equal(
    productionOrigin("http://tauri.localhost/"),
    "http://tauri.localhost",
  );
  assert.equal(
    productionOrigin("https://tauri.localhost/index.html"),
    "https://tauri.localhost",
  );
});

test("Vite, browser error pages and lookalike hosts fail before waiting for login", () => {
  for (const url of [
    "http://127.0.0.1:29346/",
    "http://localhost:29346/",
    "about:blank",
    "chrome-error://chromewebdata/",
    "http://tauri.localhost.evil/",
    "http://tauri.localhost:29346/",
    "http://user@tauri.localhost/",
    "not a URL",
  ]) {
    assert.throws(() => productionOrigin(url), /RELEASE_FRONTEND_ORIGIN_/);
  }
});
