import test from 'node:test';
import assert from 'node:assert/strict';
import { moveLine } from '../src/state/reorder.ts';
import { draftReducer, emptyDraft, draftContext, snapshot } from '../src/state/draft.ts';
import type { DraftLine } from '../src/state/draft.ts';
const goods: DraftLine={id:'goods',source:'persisted-goods',frozen:{product_id:'P',sale:'10',k:'1',single:true},raw:{line_kind:'normal',product_id:'P',q:'1',h:'',w:'',name:''}};
const discount: DraftLine={id:'discount',source:'persisted-discount',raw:{line_kind:'discount',percent:'50%',name:''}};
test('moving discount changes request order and invalidates quote without losing frozen sources',()=>{
 const draft={...emptyDraft(),lines:[goods,discount],priceVersion:'v1'};
 const next=draftReducer(draft,{type:'edit',lines:moveLine(draft.lines,'discount',0)});
 assert.equal(next.lines[1],goods);assert.equal(next.lines[0],discount);
 assert.deepEqual(draftContext(next).sources,['persisted-discount','persisted-goods']);
 assert.equal(snapshot(next).lines[0].line_kind,'discount');
 assert.equal(next.calculation,null);assert.notEqual(next.revision,draft.revision);
 assert.equal(moveLine(next.lines,'goods',-1),next.lines);
 assert.equal(moveLine(next.lines,'missing',0),next.lines);
});
test('customer-only selection does not invalidate unchanged pricing context',()=>{
 const draft={...emptyDraft(),lines:[goods,discount],calculatedRevision:'1'};
 const next=draftReducer(draft,{type:'link_customer',details:{customer:'matched',wechat:'wechat',order_ref:'new'},customer:{customer_id:'existing'}});
 assert.equal(next.revision,draft.revision);assert.equal(next.calculatedRevision,draft.calculatedRevision);
 assert.deepEqual(snapshot(next),snapshot(draft));assert.equal(next.customer?.customer_id,'existing');
});
