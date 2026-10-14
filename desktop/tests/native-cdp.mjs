// Native verification transport only; never an application IPC fallback.
export async function connectNativeBrowser(connect, endpoint, {
  timeoutMs = 30000,
  attemptTimeoutMs = 2000,
  retryDelayMs = 200,
  report = () => {},
} = {}) {
  const started = performance.now();
  let attempts = 0;
  let lastError = "No connection attempt completed";
  while (performance.now() - started < timeoutMs) {
    const remaining = timeoutMs - (performance.now() - started);
    attempts++;
    let browser;
    try {
      browser = await connect(endpoint, { timeout: Math.max(1, Math.min(attemptTimeoutMs, remaining)) });
    } catch (error) {
      lastError = String(error);
      report({ status: "connecting", endpoint, attempts, last_error: lastError, elapsed_ms: Math.round(performance.now() - started) });
    }
    if (browser) {
      try {
        report({ status: "connected", endpoint, attempts, browser_version: browser.version?.() ?? null, elapsed_ms: Math.round(performance.now() - started) });
      } catch (error) {
        await browser.close().catch(() => {});
        throw error;
      }
      return browser;
    }
    const remainingDelay = timeoutMs - (performance.now() - started);
    if (remainingDelay > 0) await new Promise((resolve) => setTimeout(resolve, Math.min(retryDelayMs, remainingDelay)));
  }
  report({ status: "failed", endpoint, attempts, last_error: lastError, elapsed_ms: Math.round(performance.now() - started) });
  throw Error("ACTUAL_WEBVIEW2_NOT_READY: " + lastError);
}
