import { request } from "../bridge";
import type { Draft } from "./draft";

export type UiEvent = "edit_requested" | "edit_resumed" | "edit_loaded" |
  "draft_switch_requested" | "draft_switch_confirmed" | "draft_continued" |
  "save_requested" | "save_confirmed" | "draft_context" | "frontend_error";
const errorKinds: Record<string, string> = {
  TypeError: "type_error", ReferenceError: "reference_error", RangeError: "range_error",
  SyntaxError: "syntax_error", Error: "error",
};

// Fixed event names and operational metadata only. Never log error messages,
// customer information, raw drafts, request bodies or credentials.
export function uiDiagnostic(event: UiEvent, draft?: Draft, error?: unknown) {
  const value = error instanceof Error ? error : undefined;
  const stack = value?.stack?.split("\n").slice(1).join("\n") ?? "";
  const source = stack.includes("useWorkbench.") ? "workbench" :
    stack.includes("/draft.") ? "draft" : stack.includes("QuotePage.") ? "quote" :
    stack.includes("DetailPage.") ? "detail" : stack.includes("/App.") ? "application" : "other";
  const position = stack.match(/\.(?:tsx?|js):(\d+):(\d+)/);
  void request("ui_diagnostic", {
    event,
    ...(draft ? { order_id: draft.editing?.order_id, revision: draft.editing?.revision,
      draft_revision: draft.revision, lines: draft.lines.length } : {}),
    ...(error === undefined ? {} : { error_kind: errorKinds[value?.name ?? ""] ?? "unknown",
      source, line: position ? Number(position[1]) : 0, column: position ? Number(position[2]) : 0 }),
  }).catch(() => {});
}

export function installUiDiagnostics() {
  const onError = (event: ErrorEvent) => uiDiagnostic("frontend_error", undefined, event.error ?? {});
  const onRejection = (event: PromiseRejectionEvent) => uiDiagnostic("frontend_error", undefined, event.reason ?? {});
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
