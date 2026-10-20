import {test,expect} from '@playwright/test';
import {nativeClient,nativeAction,nativeHost} from './fixtures/native-client';

test.afterEach(async({request})=>{expect((await request.post(nativeHost+'/cleanup',{data:{}})).ok()).toBe(true);});
test('real Rust IPC deletes a failed Host export and immediately allows quoting again',async({page,request})=>{
  await nativeClient(page,request);
  const orders=await nativeAction(page,{action:'orders',q:'',state:'',offset:0,view:''});
  const order=await nativeAction(page,{action:'order',order_id:orders.orders[0].order_id});
  expect((await request.post(nativeHost+'/block-output-directory',{data:{}})).ok()).toBe(true);
  const job=await nativeAction(page,{action:'create_output',order_id:order.order_id,expected_revision:String(order.revision),kind:'excel_quote'});
  await expect.poll(async()=>{
    const listing=await nativeAction(page,{action:'outputs',offset:0});
    return listing.jobs.find((j:any)=>j.job_id===job.job_id)?.state;
  }).toBe('failed');
  await page.getByRole('navigation').getByRole('button',{name:'导出记录',exact:true}).click();
  await page.getByRole('button',{name:'删除记录',exact:true}).click();
  await expect(page.getByRole('button',{name:'删除记录',exact:true})).toHaveCount(0);
  expect((await nativeAction(page,{action:'connection'})).pending).toBe(false);
  expect((await nativeAction(page,{action:'outputs',offset:0})).total).toBe(0);
  expect(await nativeAction(page,{action:'order',order_id:order.order_id})).toEqual(order);
  await page.getByRole('navigation').getByRole('button',{name:'报价工作台',exact:true}).click();
  await page.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  await page.getByLabel('第1行商品',{exact:true}).selectOption('安装服务');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.getByRole('button',{name:'核对并提交订单',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'一键清除',exact:true})).toBeEnabled();
});
