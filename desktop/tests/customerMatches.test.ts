import test from 'node:test';
import assert from 'node:assert/strict';
import {customerIdentity,hasCustomerIdentity} from '../src/state/customerMatches.ts';
test('quote matching only carries field-specific Taobao and WeChat identity',()=>{
 assert.deepEqual(customerIdentity({customer:' buyer ',wechat:' wechat ',order_ref:'new-order'}),{customer:'buyer',wechat:'wechat'});
 assert.equal(hasCustomerIdentity(customerIdentity({customer:'',wechat:'',order_ref:'existing-order'})),false);
 assert.equal(hasCustomerIdentity({customer:'buyer',wechat:''}),true);
 assert.equal(hasCustomerIdentity({customer:'',wechat:'wechat'}),true);
});

import {draftReducer,emptyDraft} from '../src/state/draft.ts';
test('changing identity clears an old customer choice; changing only the order number preserves it',()=>{
 const original={...emptyDraft(),details:{customer:'buyer',wechat:'wx',order_ref:'one'},customer:{customer_id:'chosen'}};
 const numbered=draftReducer(original,{type:'edit',details:{...original.details,order_ref:'two'}});
 assert.deepEqual(numbered.customer,{customer_id:'chosen'});
 for(const details of [{...original.details,customer:'other'},{...original.details,wechat:'other'}]){
   assert.equal(draftReducer(original,{type:'edit',details}).customer,undefined);
 }
});
