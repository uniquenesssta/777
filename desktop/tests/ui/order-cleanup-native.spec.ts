import {test,expect} from '@playwright/test';
import {nativeClient,nativeAction,nativeHost} from './fixtures/native-client';
test.afterEach(async({request})=>{expect((await request.post(nativeHost+'/cleanup',{data:{}})).ok()).toBe(true);});
// The isolated native fixture has no developer launcher; UI interaction is covered separately.
test('native IPC and HTTPS delete a real order, persist history and refresh totals',async({page,request})=>{
 await nativeClient(page,request);const initial=await nativeAction(page,{action:'developer_orders',query:'',offset:0,history:false});expect(initial.orders.length).toBeGreaterThan(0);const first=initial.orders[0];
 const command={action:'delete_order',ledger_id:initial.ledger_id,request_id:await page.evaluate(()=>crypto.randomUUID()),order_id:first.order_id,expected_revision:String(first.revision),reason:'真实链路清理测试'};
 const receipt=await nativeAction(page,command);expect(receipt.result.deleted).toBe(true);expect(await nativeAction(page,command)).toEqual(receipt);
 const current=await nativeAction(page,{action:'developer_orders',query:'',offset:0,history:false});expect(Number(current.total)).toBe(Number(initial.total)-1);expect(current.orders.some((o:any)=>o.order_id===first.order_id)).toBe(false);
 const listed=await nativeAction(page,{action:'orders',q:'',state:'',offset:0,view:''});expect(Number(listed.total)).toBe(Number(current.total));expect(BigInt(listed.totals.income_cents)).toBe(BigInt(initial.totals.income_cents)-BigInt(first.income_cents));
 expect((await request.post(nativeHost+'/restart',{data:{}})).ok()).toBe(true);const history=await nativeAction(page,{action:'developer_orders',query:'',offset:0,history:true});expect(history.orders[0].order_id).toBe(first.order_id);expect(history.orders[0].reason).toBe('真实链路清理测试');expect(await nativeAction(page,command)).toEqual(receipt);
});
