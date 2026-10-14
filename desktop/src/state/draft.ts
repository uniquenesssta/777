import type { Calculation, RawLine } from "../contracts";
export interface DraftLine {
  id: string;
  raw: RawLine;
}
export interface Draft {
  revision: string;
  details: { customer: string; order_ref: string; wechat: string };
  lines: DraftLine[];
  priceVersion: string;
  calculation: Calculation | null;
  calculatedRevision: string | null;
}
export const emptyDraft = (): Draft => ({
  revision: "1",
  details: { customer: "", order_ref: "", wechat: "" },
  lines: [],
  priceVersion: "",
  calculation: null,
  calculatedRevision: null,
});
export type DraftAction =
  | { type: "edit"; details?: Draft["details"]; lines?: DraftLine[] }
  | { type: "prices"; version: string }
  | { type: "calculated"; revision: string; result: Calculation }
  | { type: "invalidate" }
  | { type: "reset" }
  | { type: "committed"; snapshot: unknown; details: unknown };
export function draftReducer(d: Draft, a: DraftAction): Draft {
  if (a.type === "reset") return emptyDraft();
  if (a.type === "committed") {
    const matches =
      stableRaw(snapshot(d)) === stableRaw(a.snapshot) &&
      stableRaw(d.details) === stableRaw(a.details);
    return {
      ...(matches ? emptyDraft() : d),
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
      p.lines.length > 1000 ||
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
    return { ...fresh, lines: p.lines, details: p.details };
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
