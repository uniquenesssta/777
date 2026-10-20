import { request } from "../bridge";
import type { Draft } from "./draft";
export interface SavedInput {
  snapshot: unknown; details: unknown; order_id?: string|null;
  expected_revision?: string|null; sources?: unknown; customer?: unknown;
}
export interface LocalSaveReceipt {result:{order_id:string}|null;submitted?:SavedInput|null}
export function persistDraft(draft:Draft,source:string|null) {
  localStorage.setItem("777-desktop-draft-v1",JSON.stringify({schema:"777-desktop-draft-v1",save_id:draft.saveId,price_version_id:draft.priceVersion,
    ...(source?{source_pin:source}:{}),details:draft.details,lines:draft.lines,editing:draft.editing,customer:draft.customer}));
}
export async function savedDraft(id:string):Promise<LocalSaveReceipt|null> {
  // Older online-only/native test bridges have no local command receipt.
  return request<LocalSaveReceipt>("local_receipt",{operation_id:id}).catch(()=>null);
}
export function savedContext(input:SavedInput) {
  return {order_id:input.order_id??null,expected_revision:input.expected_revision??null,sources:input.sources,customer:input.customer??{}};
}
