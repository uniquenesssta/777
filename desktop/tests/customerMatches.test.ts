import test from 'node:test';
import assert from 'node:assert/strict';
import {customerQueries,mergeCustomerMatches} from '../src/state/customerMatches.ts';
import type {CustomerListing,CustomerGroup} from '../src/contracts.ts';
test('matching uses all current identifiers after restore and deduplicates queries and customers',()=>{
 assert.deepEqual(customerQueries({customer:' buyer ',wechat:'wechat',order_ref:'new-order'}),['buyer','wechat','new-order']);
 assert.deepEqual(customerQueries({customer:'same',wechat:'same',order_ref:''}),['same']);
 const group={group_id:'buyer',orders:[{order_id:'order'}]} as CustomerGroup;
 const page={groups:[group],offset:0,limit:20,total:1} as CustomerListing;
 const result=mergeCustomerMatches([page,page]);assert.equal(result.groups.length,1);assert.equal(result.groups[0].orders.length,1);assert.equal(result.has_more,false);
 assert.equal(mergeCustomerMatches([{...page,total:21}]).has_more,true);
});
