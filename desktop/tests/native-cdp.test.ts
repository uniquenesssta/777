import test from "node:test";
import assert from "node:assert/strict";
import { connectNativeBrowser } from "./native-cdp.mjs";

test("native readiness preserves the underlying CDP error and attempt diagnostics", async () => {
  const records: Record<string, unknown>[] = [];
  await assert.rejects(connectNativeBrowser(async () => { throw Error("connect ECONNREFUSED 127.0.0.1:49152"); }, "http://127.0.0.1:49152", {
    timeoutMs: 20, retryDelayMs: 1, report: (v: Record<string, unknown>) => records.push(v),
  }), /ACTUAL_WEBVIEW2_NOT_READY: Error: connect ECONNREFUSED/);
  assert.equal(records.at(-1)?.status, "failed");
  assert.match(String(records.at(-1)?.last_error), /ECONNREFUSED/);
  assert.ok(Number(records.at(-1)?.attempts) > 0);
});

test("native readiness succeeds after transient refusal and bounds each connect attempt", async () => {
  let calls = 0;
  const browser = { version: () => "152.test" };
  let observedVersion;
  const result = await connectNativeBrowser(async (_endpoint: string, options: { timeout: number }) => {
    assert.ok(options.timeout > 0 && options.timeout <= 7);
    if (++calls === 1) throw Error("not listening yet");
    return browser;
  }, "http://127.0.0.1:49152", { timeoutMs: 100, attemptTimeoutMs: 7, retryDelayMs: 1,
    report: (value: { browser_version?: string }) => { observedVersion = value.browser_version; } });
  assert.equal(result, browser);
  assert.equal(calls, 2);
  assert.equal(observedVersion, "152.test");
});

test("a failed connection checkpoint closes the attached browser and does not retry", async () => {
  let calls = 0, closes = 0;
  await assert.rejects(connectNativeBrowser(async () => {
    calls++;
    return { close: async () => { closes++; } };
  }, "http://127.0.0.1:49152", { report: () => { throw Error("checkpoint failed"); } }), /checkpoint failed/);
  assert.equal(calls, 1);
  assert.equal(closes, 1);
});
