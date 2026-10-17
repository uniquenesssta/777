import test from "node:test";
import assert from "node:assert/strict";
import { uiDiagnostic, installUiDiagnostics } from "../src/state/uiDiagnostics.ts";
import { emptyDraft } from "../src/state/draft.ts";

test("UI diagnostics record fixed metadata without customer, cost, message or stack text", async () => {
  const calls: Record<string, unknown>[] = [];
  const handlers = new Map<string, (event: unknown) => void>();
  Object.assign(globalThis, { window: {
    __TAURI_INTERNALS__: { invoke: (_: string, args: {request: Record<string,unknown>}) => {
      calls.push(args.request); return Promise.resolve(null);
    } },
    addEventListener: (name: string, handler: (e:unknown)=>void) => handlers.set(name, handler),
    removeEventListener: (name: string) => handlers.delete(name),
  } });
  const error = new TypeError("password=secret customer=private cost=999");
  error.stack = "TypeError: private content\n at submit (http://localhost/src/state/useWorkbench.ts:52:8)";
  uiDiagnostic("frontend_error", {...emptyDraft(),details:{customer:"private-customer",order_ref:"private-number",wechat:"private-wechat"}},error);
  await Promise.resolve();
  assert.equal(calls[0].error_kind,"type_error");
  assert.equal(calls[0].source,"workbench");
  assert.equal(calls[0].line,52);
  assert.equal(calls[0].column,8);
  assert.doesNotMatch(JSON.stringify(calls),/password|secret|private|cost|localhost/);
  const cleanup=installUiDiagnostics();
  handlers.get("error")!({error});handlers.get("unhandledrejection")!({reason:error});
  await Promise.resolve();
  assert.equal(calls.length,3);
  cleanup();assert.equal(handlers.size,0);
});
