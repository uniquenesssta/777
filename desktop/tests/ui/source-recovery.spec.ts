import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
const managerPages=['报价工作台','订单记录','价格维护','利润分析','导出记录','存储与备份'];
for(const delivery of ['development','manager','sales']) {
  test(`${delivery} navigation survives missing session and remains permission-scoped`,async({page})=>{
    await page.clock.install();
    await setup(page,delivery,delivery==='sales'?['quote','orders']:null,false);
    for(const name of delivery==='sales'?['报价工作台','我的订单']:managerPages)
      await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name,exact:true})).toBeVisible();
    if(delivery==='sales')for(const name of ['价格维护','利润分析','导出记录','存储与备份'])
      await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name,exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:delivery==='sales'?'我的订单':'订单记录',exact:true}).click();
    await expect(page.getByRole('heading',{name:delivery==='sales'?/^我的订单/:/^订单记录/})).toBeVisible();
    await page.clock.fastForward(5000);
    await expect(page.getByRole('heading',{name:delivery==='sales'?/^我的订单/:/^订单记录/})).toBeVisible();
    await page.getByRole('button',{name:'报价工作台',exact:true}).click();
    await expect(page.getByRole('button',{name:'计算报价',exact:true})).toBeDisabled();
    expect(await page.evaluate(()=>(window as any).__requests.some((r:any)=>['save_order','orders'].includes(r.action)))).toBe(false);
  });
}
test('local recovery selects launcher ledger without reusing remote address or certificate',async({page},info)=>{
  await setup(page,'development',null,false);
  await page.getByRole('button',{name:'开发数据',exact:true}).click();
  await page.getByRole('button',{name:'选择或更换后台连接',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('服务地址',{exact:true}).fill('https://127.0.0.1:18477');
  await page.evaluate(()=>{
    const api=(window as any).__TAURI_INTERNALS__;const old=api.invoke;
    api.invoke=async(command:string,args:any)=>{
      if(args?.request?.action==='developer'&&args.request.request.op==='select')
        sessionStorage.setItem('tested-local-select',JSON.stringify(args.request));
      return old(command,args);
    };
  });
  await page.setViewportSize({width:720,height:600});
  await dialog.getByRole('button',{name:'切回本机开发数据',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:info.outputPath('local-recovery-720.png')});
  await dialog.getByRole('button',{name:'切回本机开发数据',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>sessionStorage.getItem('tested-local-select'))).not.toBeNull();
  const selected=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('tested-local-select')!));
  expect(selected.request).toEqual({op:'select',root:'D:\\Dev',backup_dir:'D:\\Backup',initialize:false,username:null,password:null});
});
