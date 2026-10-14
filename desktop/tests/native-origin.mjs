// Shared by the native WebView2 smoke and its origin regression tests.
export function productionOrigin(raw) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw Error("RELEASE_FRONTEND_ORIGIN_INVALID");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.hostname !== "tauri.localhost" ||
    url.port ||
    url.username ||
    url.password
  ) {
    throw Error("RELEASE_FRONTEND_ORIGIN_REJECTED: " + url.origin);
  }
  return url.origin;
}
