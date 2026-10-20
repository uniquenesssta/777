// Real UI wiring; local cryptographic signing and registration are native protocol tests.
import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';

test('local packaging has no server approval, login or Host import step',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__issuerError='ISSUER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED');
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await expect(page.getByText('在本机完成封包，无需连接服务器。',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'封包授权',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'封包母版',exact:true}).click();
  await page.getByRole('button',{name:'子版',exact:true}).click();
  await page.getByRole('button',{name:'封包子版',exact:true}).click();
  const requests=await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='developer'));
  expect(requests.filter((r:any)=>r.request.op==='package').map((r:any)=>r.request.delivery)).toEqual(['manager','sales']);
  expect(requests.some((r:any)=>r.request.op.startsWith('issuer_'))).toBe(false);
});

test('unreadable local signer blocks signing without offering server authorization or identity reset',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__issuerState={ready:false,phase:'unavailable',interfaces:[],error:'LOCAL_SIGNER_UNAVAILABLE'});
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await expect(page.getByRole('button',{name:'封包母版',exact:true})).toBeDisabled();
  await expect(page.getByText('本机签发身份暂不可用，请检查开发日志。',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:/授权|升级包/})).toHaveCount(0);
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
  await expect(page.getByRole('button',{name:'封包母版',exact:true})).toBeEnabled();
});
