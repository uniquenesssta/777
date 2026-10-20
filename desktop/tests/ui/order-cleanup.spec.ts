import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
async function screen(page:any){
 await setup(page,'development');
 await page.addInitScript(()=>{const api=(window as any).__TAURI_INTERNALS__,original=api.invoke;const order={order_id:'00000000-0000-4000-8000-000000000001',revision:'1',details:{customer:'淘宝测试客户',wechat:'wx_demo',order_ref:'TEST-01'},income_cents:'12000'};let deleted=false;
 api.invoke=async(command:string,args:any)=>{const r=args?.request;if(!['developer_orders','delete_order'].includes(r?.action))return original(command,args);(window as any).__requests.push(r);
 if(r.action==='delete_order'){if((window as any).__deleteFailure){const error=(window as any).__deleteFailure;(window as any).__deleteFailure=false;throw{code:typeof error==='string'?error:'SERVICE_RESPONSE_INCOMPLETE'};}deleted=true;return{ledger_id:'fixture-ledger',result:{deleted:true}};}
 const orders=r.history?(deleted?[{...order,deleted_at:'2026-10-20T16:00:00Z',deleted_by:'fixture',reason:'清理测试'}]:[]):deleted?[]:[order];return{ledger_id:'fixture-ledger',orders,total:orders.length,offset:0,limit:20};};});
 await page.goto('/');await page.getByRole('button',{name:'开发者工具',exact:true}).click();await page.getByRole('button',{name:'订单清理',exact:true}).click();
}
test('confirmation identifies the ledger, retries the same request and exposes immutable history',async({page},info)=>{
 await screen(page);await expect(page.getByText('淘宝测试客户',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'删除订单',exact:true}).click();const dialog=page.getByRole('dialog');await expect(dialog).toContainText('fixture-ledger');await expect(dialog.getByRole('button',{name:'确认删除'})).toBeDisabled();
 await dialog.getByLabel('删除原因').fill('清理测试');await page.evaluate(()=>(window as any).__deleteFailure=true);await dialog.getByRole('button',{name:'确认删除'}).click();await expect(dialog.getByRole('alert')).toBeVisible();await expect(page.getByText('淘宝测试客户',{exact:true})).toBeVisible();
 await page.screenshot({path:info.outputPath('delete-confirmation.png')});await dialog.getByRole('button',{name:'重试删除'}).click();await expect(dialog).toHaveCount(0);await expect(page.getByText('没有找到订单')).toBeVisible();
 const calls=await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='delete_order'));expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0]);expect(calls[0]).toMatchObject({ledger_id:'fixture-ledger',expected_revision:'1',reason:'清理测试'});
 await page.getByRole('button',{name:'删除记录',exact:true}).click();await expect(page.getByText('原因：清理测试')).toBeVisible();await expect(page.getByRole('button',{name:'删除订单',exact:true})).toHaveCount(0);
 await page.setViewportSize({width:720,height:600});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('deletion-history.png')});
});
test('cancelling deletion leaves the order; visible copy does not name an administrator',async({page})=>{
 await screen(page);await page.getByRole('button',{name:'删除订单',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();expect(await page.evaluate(()=>(window as any).__requests.some((r:any)=>r.action==='delete_order'))).toBe(false);
 await page.getByRole('button',{name:'存储与备份',exact:true}).click();await expect(page.getByPlaceholder('已发布的保存位置')).toHaveCount(2);await expect(page.locator('body')).not.toContainText('管理员');
});

test('concurrent edits require a fresh read instead of repeatedly submitting a stale revision',async({page})=>{
 await screen(page);await page.getByRole('button',{name:'删除订单',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByLabel('删除原因').fill('清理测试');await page.evaluate(()=>(window as any).__deleteFailure='REVISION_OR_PRICE_CONFLICT');await dialog.getByRole('button',{name:'确认删除'}).click();await expect(dialog.getByRole('alert')).toContainText('订单已被修改');await dialog.getByRole('button',{name:'重新读取订单'}).click();await expect(dialog).toHaveCount(0);await expect(page.getByRole('button',{name:'删除订单',exact:true})).toBeEnabled();expect(await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='delete_order').length)).toBe(1);
});
