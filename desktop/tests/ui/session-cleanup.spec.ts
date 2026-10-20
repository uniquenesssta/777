import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
import {orderRecords} from './fixtures/order-records-bridge';

test('quote survives navigation and page reload but a new native runtime starts empty',async({page},info)=>{
  await setup(page,'manager');
  await page.getByLabel('客户 / 淘宝 ID',{exact:true}).fill('本次运行客户');
  await page.getByLabel('订单号',{exact:true}).fill('session-order');
  await page.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  await page.getByRole('navigation').getByRole('button',{name:'订单记录',exact:true}).click();
  await page.getByRole('navigation').getByRole('button',{name:'报价工作台',exact:true}).click();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('session-order');
  await page.reload();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('session-order');
  await page.getByRole('button',{name:'一键清除',exact:true}).click();
  await expect(page.getByLabel('客户 / 淘宝 ID',{exact:true})).toHaveValue('');
  await expect(page.getByLabel('第1行商品',{exact:true})).toHaveCount(0);
  await page.getByLabel('订单号',{exact:true}).fill('must-not-restore');
  await page.evaluate(()=>{localStorage.setItem('777-desktop-draft-v1',sessionStorage.getItem('777-desktop-draft-v1')!);sessionStorage.setItem('fixture-runtime','new-runtime');});
  await page.reload();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('');
  expect(await page.evaluate(()=>localStorage.getItem('777-desktop-draft-v1'))).toBeNull();
  await page.screenshot({path:info.outputPath('quote-clear.png')});
});

test('order view switches retain loaded customer data without another query and clear does not delete an edited order',async({page})=>{
  await orderRecords(page);
  await page.getByRole('button',{name:'按客户查看',exact:true}).click();
  await expect(page.locator('.customer-group')).toHaveCount(2);
  const count=()=>page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='customer_orders').length);
  const initial=await count();
  await page.getByRole('button',{name:'全部订单',exact:true}).click();
  await page.getByRole('button',{name:'按客户查看',exact:true}).click();
  await expect(page.locator('.customer-group').first()).toBeVisible();
  expect(await count()).toBe(initial);
  await page.locator('.customer-group').nth(1).getByRole('button',{name:'继续编辑',exact:true}).click();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('QH-2');
  await page.getByRole('button',{name:'一键清除',exact:true}).click();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('');
  await page.getByRole('navigation').getByRole('button',{name:'订单记录',exact:true}).click();
  await expect(page.getByRole('table',{name:'全部订单',exact:true})).toContainText('QH-2');
});

test('failed output deletion calls native mutation, updates the list and leaves completed outputs alone',async({page})=>{
  await setup(page,'manager');
  await page.evaluate(()=>{
    const api=(window as any).__TAURI_INTERNALS__,old=api.invoke;
    let failed=true;
    api.invoke=async(cmd:string,args:any)=>{
      if(args?.request?.action==='delete_output'){(window as any).__deletedOutput=args.request;failed=false;return{deleted:true};}
      const value=await old(cmd,args);
      if(args?.request?.action==='outputs')return {...value,total:failed?2:1,jobs:value.jobs.slice(0,failed?2:1).map((j:any,i:number)=>({...j,state:failed&&i===1?'failed':'done'}))};
      return value;
    };
  });
  await page.getByRole('navigation').getByRole('button',{name:'导出记录',exact:true}).click();
  await expect(page.getByRole('button',{name:'删除记录',exact:true})).toHaveCount(1);
  await page.getByRole('button',{name:'删除记录',exact:true}).click();
  await expect(page.getByRole('button',{name:'删除记录',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'打开文件夹',exact:true})).toHaveCount(1);
  expect(await page.evaluate(()=>(window as any).__deletedOutput)).toMatchObject({action:'delete_output',job_id:'job-1'});
});

test('package cleanup previews actual targets and only executes on confirmation',async({page},info)=>{
  await setup(page,'development');
  await page.getByRole('navigation').getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.evaluate(()=>{
    const api=(window as any).__TAURI_INTERNALS__,old=api.invoke;
    api.invoke=async(cmd:string,args:any)=>{
      if(args?.request?.request?.op==='package_cleanup_preview')return{count:1,outputs:['D:\\Packages\\manager-1.0.0-12345678']};
      if(args?.request?.request?.op==='clear_packages')(window as any).__cleaned=true;
      return old(cmd,args);
    };
  });
  await page.getByRole('button',{name:'清除所有封包',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog).toContainText('D:\\Packages\\manager-1.0.0-12345678');
  expect(await page.evaluate(()=>(window as any).__cleaned)).toBeUndefined();
  await page.screenshot({path:info.outputPath('package-cleanup.png')});
  await dialog.getByRole('button',{name:'确认清除'}).click();
  await expect(dialog).toHaveCount(0);
  expect(await page.evaluate(()=>(window as any).__cleaned)).toBe(true);
});
