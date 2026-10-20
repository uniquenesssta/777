// UI wiring and layout only; real TLS stage classification is covered by the native test.
import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';

test('failed authorization retries and opens the same kit; regeneration is a separate explicit choice',async({page},info)=>{
  await setup(page,'development');
  await page.evaluate(()=>{
    (window as any).__issuerState={ready:false,phase:'pending',interfaces:['192.168.4.80','192.168.4.81']};
    (window as any).__issuerError='ISSUER_PAIR_UNREACHABLE_OR_CERTIFICATE_REJECTED';
  });
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await expect(page.getByRole('button',{name:'封包母版',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'完成封包授权',exact:true}).click();
  const retry=page.getByRole('button',{name:'连接 4.23 完成授权',exact:true});
  await retry.click();
  await expect(page.getByRole('alert')).toContainText('8478');
  await retry.click();
  await page.getByRole('button',{name:'打开原升级包',exact:true}).click();
  const ops=await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='developer').map((r:any)=>r.request.op));
  expect(ops.filter((v:string)=>v==='issuer_connect')).toHaveLength(2);
  expect(ops).toContain('issuer_open');expect(ops).not.toContain('issuer_prepare');
  await retry.click();
  expect(await page.locator('.developer-title').evaluate(el=>{
    const title=el.querySelector('h1')!.getBoundingClientRect();
    return Math.abs(title.left-el.getBoundingClientRect().left)<2;
  })).toBe(true);
  await page.screenshot({path:info.outputPath('issuer-retry.png')});
  await page.getByText('更换升级包',{exact:true}).click();
  await page.getByRole('button',{name:'重新生成升级包',exact:true}).click();
  const confirm=page.getByRole('button',{name:'确认生成新升级包',exact:true});
  await expect(confirm).toBeDisabled();
  await page.getByLabel('192.168.4.80',{exact:true}).check();
  await confirm.click();
  const call=await page.evaluate(()=>(window as any).__requests.find((r:any)=>r.request?.op==='issuer_prepare'));
  expect(call.request).toMatchObject({restart:true,peer:'192.168.4.80'});
});

test('unreadable authorization state cannot be mistaken for a first preparation',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__issuerState={ready:false,phase:'unavailable',interfaces:[],error:'ISSUER_STATUS_UNAVAILABLE'});
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.getByRole('button',{name:'封包授权',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('暂时无法读取');
  await expect(page.getByRole('button',{name:'生成主机升级包',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'刷新授权状态',exact:true})).toBeEnabled();
});

test('empty lists, report actions and compact maintenance remain usable at different sizes',async({page},info)=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__jobCount=0);
  for(const size of [{width:1476,height:860},{width:1476,height:1200},{width:390,height:600}]){
    await page.setViewportSize(size);
    await page.getByRole('button',{name:'导出记录',exact:true}).click();
    const form=page.locator('.report-filters');
    expect(await form.getByRole('button',{name:'导出 Excel'}).evaluate(el=>el.getBoundingClientRect().height)).toBe(40);
    const list=page.locator('.tasks-card>.orders-table-scroll');
    await expect.poll(()=>list.evaluate(el=>{const b=el.getBoundingClientRect(),t=el.querySelector('table')!.getBoundingClientRect(),e=el.querySelector('.empty')!.getBoundingClientRect();return Math.abs((e.top+e.bottom)/2-(t.bottom+b.bottom)/2)<2;})).toBe(true);
    await page.getByRole('button',{name:'下一页',exact:true}).scrollIntoViewIfNeeded();
    await expect(page.getByRole('button',{name:'下一页',exact:true})).toBeInViewport();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`exports-${size.width}-${size.height}.png`)});
  }
  await page.setViewportSize({width:1476,height:1200});
  await page.getByRole('button',{name:'订单记录',exact:true}).click();
  const actions=page.locator('.orders-card .section-actions');
  expect(await actions.evaluate(el=>el.getBoundingClientRect().width)).toBeLessThan(240);
  await page.screenshot({path:info.outputPath('orders-empty.png')});
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.getByRole('button',{name:'封包授权',exact:true}).click();
  expect(await page.locator('.issuer-panel').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThan(350);
});
