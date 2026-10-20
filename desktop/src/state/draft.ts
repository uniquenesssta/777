import type { Calculation, RawLine, Order, CustomerChoice } from "../contracts";
export interface DraftLine {
  id: string;
  raw: RawLine;
  source?: string;
  frozen?: {product_id:string;sale:string;k:string;single:boolean};
}
export interface Draft {
  saveId: string;
  editing?: {order_id:string;revision:string};
  customer?: CustomerChoice;
  revision: string;
  details: { customer: string; order_ref: string; wechat: string };
  lines: DraftLine[];
  priceVersion: string;
  calculation: Calculation | null;
  calculatedRevision: string | null;
}
export const emptyDraft = (): Draft => ({
  saveId: crypto.randomUUID(),
  revision: "1",
  details: { customer: "", order_ref: "", wechat: "" },
  lines: [],
  priceVersion: "",
  calculation: null,
  calculatedRevision: null,
});
export type DraftAction =
  | { type: "restore"; raw: string | null }
  | { type: "load_order"; order:Order }
  | { type: "customer"; details:Draft["details"]; customer:CustomerChoice }
  | { type: "link_customer"; details:Draft["details"]; customer:CustomerChoice }
  | { type: "edit"; details?: Draft["details"]; lines?: DraftLine[] }
  | { type: "prices"; version: string }
  | { type: "calculated"; revision: string; result: Calculation }
  | { type: "invalidate" }
  | { type: "reset" }
  | { type: "committed"; snapshot: unknown; details: unknown; context?:unknown };
export function draftReducer(d: Draft, a: DraftAction): Draft {
  if (a.type === "restore") return restorableDraft(a.raw);
  if (a.type === "reset") return {...emptyDraft(),priceVersion:d.priceVersion};
  if (a.type === "load_order") return {...emptyDraft(), priceVersion:d.priceVersion, revision:(BigInt(d.revision)+1n).toString(), editing:{order_id:a.order.order_id,revision:a.order.revision}, customer:a.order.customer_id?{customer_id:a.order.customer_id}:{}, details:a.order.details, lines:a.order.lines.map(l=>({id:crypto.randomUUID(),raw:l.raw,source:l.line_id,frozen:l.raw.line_kind==="normal"?{product_id:l.raw.product_id,sale:String(l.normalized.sale??""),k:String(l.normalized.k??"1"),single:l.normalized.h===undefined}:undefined}))};
  if (a.type === "link_customer") return {...d,details:a.details,customer:a.customer,revision:(BigInt(d.revision)+1n).toString(),calculation:null,calculatedRevision:null};
  if (a.type === "customer") return {...emptyDraft(),priceVersion:d.priceVersion,revision:(BigInt(d.revision)+1n).toString(),details:a.details,customer:a.customer};
  if (a.type === "committed") {
    const matches =
      stableRaw(snapshot(d)) === stableRaw(a.snapshot) &&
      stableRaw(d.details) === stableRaw(a.details) &&
      (a.context === undefined ? !d.editing : stableRaw(draftContext(d)) === stableRaw(a.context));
    return {
      ...(matches ? emptyDraft() : d),
      saveId: crypto.randomUUID(),
      priceVersion: d.priceVersion,
      revision: (BigInt(d.revision) + 1n).toString(),
      calculation: null,
      calculatedRevision: null,
    };
  }
  if (a.type === "calculated")
    return a.revision === d.revision &&
      a.result.price_version_id === d.priceVersion
      ? { ...d, calculation: a.result, calculatedRevision: a.revision }
      : d;
  return {
    ...d,
    ...(a.type === "edit"
      ? { details: a.details ?? d.details, lines: a.lines ?? d.lines }
      : {}),
    priceVersion: a.type === "prices" ? a.version : d.priceVersion,
    revision: (BigInt(d.revision) + 1n).toString(),
    calculation: null,
    calculatedRevision: null,
  };
}
export function draftContext(d:Draft){return {order_id:d.editing?.order_id??null,expected_revision:d.editing?.revision??null,sources:d.lines.map(l=>l.source??null),customer:d.customer??{}};}
export function snapshot(d: Draft) {
  return {
    price_version_id: d.priceVersion,
    rule_version: "business-v1",
    numeric_profile: "numeric-v1",
    lines: d.lines.map((l) => l.raw),
  };
}
export function restorableDraft(raw: string | null): Draft {
  const fresh = emptyDraft();
  if (!raw) return fresh;
  try {
    const p = JSON.parse(raw);
    if (
      p.schema !== "777-desktop-draft-v1" ||
      !Array.isArray(p.lines) ||
      p.lines.length > 10000 ||
      !p.details
    )
      return fresh;
    const valid = p.lines.every(
      (l: DraftLine) =>
        typeof l.id === "string" &&
        l.raw &&
        ["normal", "discount"].includes(l.raw.line_kind) &&
        Object.values(l.raw).every(
          (x) => typeof x === "string" && x.length <= 4096,
        ),
    );
    if (
      !valid ||
      !["customer", "order_ref", "wechat"].every(
        (k) => typeof p.details[k] === "string" && p.details[k].length <= 4096,
      )
    )
      return fresh;
    const editing = p.editing && typeof p.editing.order_id === "string" && /^\d+$/.test(p.editing.revision) ? p.editing : undefined;
    const customer = p.customer && typeof p.customer === "object" ? p.customer : undefined;
    const saveId = typeof p.save_id === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(p.save_id) ? p.save_id : fresh.saveId;
    const priceVersion = typeof p.price_version_id === "string" && p.price_version_id.length<=256 ? p.price_version_id : fresh.priceVersion;
    return { ...fresh, saveId,priceVersion, lines: p.lines, details: p.details, editing, customer };
  } catch {
    return fresh;
  }
}

function stableRaw(value: unknown): string {
  return JSON.stringify(value, (_, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v).sort(([a], [b]) => a.localeCompare(b)),
        )
      : v,
  );
}
