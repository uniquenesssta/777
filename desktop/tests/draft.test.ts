import test from "node:test";
import assert from "node:assert/strict";
import {
  draftReducer,
  emptyDraft,
  restorableDraft,
} from "../src/state/draft.ts";
import { money } from "../src/state/format.ts";
import type { Calculation } from "../src/contracts.ts";
const result: Calculation = {
  status: "ok",
  price_version_id: "v1",
  lines: [],
  totals: { income_cents: "9007199254740993" },
  issues: [],
  warnings: [],
};
test("late calculation cannot restore authority after any input or price change", () => {
  let d = draftReducer(emptyDraft(), { type: "prices", version: "v1" });
  const rev = d.revision;
  d = draftReducer(d, {
    type: "edit",
    details: { customer: "00001", order_ref: "00002", wechat: "" },
  });
  assert.equal(
    draftReducer(d, { type: "calculated", revision: rev, result }).calculation,
    null,
  );
  d = draftReducer(d, { type: "calculated", revision: d.revision, result });
  assert.equal(d.calculation?.totals?.income_cents, "9007199254740993");
  assert.equal(
    draftReducer(d, { type: "prices", version: "v2" }).calculation,
    null,
  );
});
test("revision and display cents never pass through JS floating point", () => {
  let d = { ...emptyDraft(), revision: "9007199254740993" };
  d = draftReducer(d, { type: "invalidate" });
  assert.equal(d.revision, "9007199254740994");
  assert.equal(money("9007199254740993"), "90,071,992,547,409.93");
  assert.equal(money("-1"), "-0.01");
  assert.equal(money("0"), "0.00");
});
test("only raw draft fields restore, never a claimed result or stored role", () => {
  const raw = JSON.stringify({
    schema: "777-desktop-draft-v1",
    details: { customer: "00001", order_ref: "00003", wechat: "" },
    lines: [
      {
        id: "line",
        raw: {
          line_kind: "normal",
          product_id: "P",
          h: "2cm",
          w: "3",
          q: "1",
          name: "",
        },
      },
    ],
    calculation: result,
    role: "admin",
  });
  const d = restorableDraft(raw);
  assert.equal(d.details.order_ref, "00003");
  assert.equal(d.calculation, null);
  assert.equal(d.priceVersion, "");
  assert.equal(d.calculatedRevision, null);
  assert.equal(restorableDraft("{corrupt").lines.length, 0);
});
test("confirmed original order clears only its own raw draft and preserves edits during submit", () => {
  let d = draftReducer(emptyDraft(), { type: "prices", version: "v1" });
  d = draftReducer(d, {
    type: "edit",
    details: { customer: "old", order_ref: "00003", wechat: "" },
  });
  const original = {
    price_version_id: "v1",
    rule_version: "business-v1",
    numeric_profile: "numeric-v1",
    lines: [],
  };
  const details = d.details;
  assert.equal(
    draftReducer(d, { type: "committed", snapshot: original, details }).details
      .order_ref,
    "",
  );
  d = draftReducer(d, {
    type: "edit",
    details: { ...details, order_ref: "new-00004" },
  });
  const kept = draftReducer(d, {
    type: "committed",
    snapshot: original,
    details,
  });
  assert.equal(kept.details.order_ref, "new-00004");
  assert.equal(kept.calculation, null);
  assert.ok(BigInt(kept.revision) > BigInt(d.revision));
});
test("late edit receipt cannot clear another order with identical customer and goods",()=>{
 const d={...emptyDraft(),editing:{order_id:"second",revision:"1"},details:{customer:"same",order_ref:"",wechat:""}};
 const result=draftReducer(d,{type:"committed",snapshot:{price_version_id:"",rule_version:"business-v1",numeric_profile:"numeric-v1",lines:[]},details:d.details,context:{order_id:"first",expected_revision:"1",sources:[],customer:{}}});
 assert.equal(result.editing?.order_id,"second");
});
