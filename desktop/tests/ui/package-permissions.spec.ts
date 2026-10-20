// UI wiring only. No installer or remote host is invoked by this fixture.
import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
async function top(page:import('@playwright/test').Page){await page.evaluate(()=>{scrollTo(0,0);document.querySelector('.workspace')?.scrollTo(0,0);});await expect.poll(()=>page.evaluate(()=>Math.max(scrollY,document.querySelector('.workspace')?.scrollTop??0))).toBe(0);}
test('package choices send the reviewed policy and do not require typed paths or version',async({page},info)=>{
  await setup(page,'development');
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  const card=page.locator('.packaging-workspace');
  await expect(card.locator('input[type=text]')).toHaveCount(0);
  await card.getByLabel('成本、利润与内部财务报表',{exact:true}).uncheck();
  await expect(card.getByLabel('价格维护（包含成本）',{exact:true})).not.toBeChecked();
  await card.getByRole('button',{name:'选择文件夹',exact:true}).click();
  await card.getByRole('button',{name:'封包母版',exact:true}).click();
  const requests=await page.evaluate(()=>(window as any).__requests);
  const build=requests.find((r:any)=>r.action==='developer'&&r.request.op==='package');
  expect(build.request.delivery).toBe('manager');
  expect(build.request.permissions).toEqual(['quote','orders','edit_orders','exports','settings','backup']);
  expect(requests.find((r:any)=>r.action==='developer'&&r.request.op==='save_package').request).toEqual({op:'save_package',output:'D:\\Selected',version:'0.1.0',runtime:'downloadBootstrapper'});
  expect(requests.some((r:any)=>['package_target','use_current_package_target','verify_package_target'].includes(r.action))).toBe(false);
  await top(page);
  await page.screenshot({path:info.outputPath('package-manager.png'),fullPage:true});
  await card.getByRole('button',{name:'子版',exact:true}).click();
  await expect(card.getByLabel('成本、利润与内部财务报表',{exact:true})).toHaveCount(0);
  await page.setViewportSize({width:720,height:1100});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await top(page);
  await page.screenshot({path:info.outputPath('package-choices-720.png'),fullPage:true});
});
test('choices survive data navigation; failed jobs retry without a new package request',async({page},info)=>{
  await setup(page,'development');await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  const card=page.locator('.packaging-workspace');
  await card.getByLabel('成本、利润与内部财务报表',{exact:true}).uncheck();
  await page.getByRole('button',{name:'开发数据',exact:true}).click();
  await top(page);
  await page.screenshot({path:info.outputPath('developer-data.png'),fullPage:true});
  await page.getByRole('button',{name:'应用封包',exact:true}).click();
  await expect(card.getByLabel('价格维护（包含成本）',{exact:true})).not.toBeChecked();
  await page.evaluate(()=>{(window as any).__packageJob={id:'original-job',state:'failed',delivery:'manager',version:'0.1.0',output:'D:\\Packages',permissions:['quote'],lines:['LOCAL_SIGNER_UNAVAILABLE'],error:'LOCAL_SIGNER_UNAVAILABLE',bytes:null};});
  await expect(page.getByRole('heading',{name:'封包未完成',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'重试本次封包',exact:true}).click();
  const calls=await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='developer').map((r:any)=>r.request.op));
  expect(calls).toContain('retry_package');expect(calls).not.toContain('package');
});
test('390px long paths wrap and the original check asset renders at 12px',async({page},info)=>{
  await setup(page,'development');await page.setViewportSize({width:390,height:600});
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.evaluate(()=>{(window as any).__packageOutput='D:\\'+('报价系统交付目录'.repeat(50));});
  await expect.poll(()=>page.locator('.package-path').first().textContent()).toContain('报价系统交付目录');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  const nav=await page.locator('.topbar nav .button').evaluateAll(nodes=>nodes.map(n=>({x:n.getBoundingClientRect().x,width:n.getBoundingClientRect().width})));
  expect(nav.every((n,i)=>n.width>60&&(i===0||n.x>=nav[i-1].x+nav[i-1].width))).toBe(true);
  const mark=page.locator('.package-checkbox img').first();
  await expect.poll(()=>mark.evaluate((n:HTMLImageElement)=>n.complete&&n.naturalWidth>0)).toBe(true);
  expect(await mark.evaluate(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height}))).toEqual({width:12,height:12});
  await top(page);
  await page.screenshot({path:info.outputPath('package-390-long-path.png'),fullPage:true});
});
for(const delivery of ['manager','sales'])test(`${delivery} quote-only policy has no hidden-feature navigation or account menu`,async({page})=>{
  await setup(page,delivery,['quote']);
  await expect(page.getByRole('button',{name:'报价工作台',exact:true})).toBeVisible();
  for(const name of ['账户菜单','退出登录','订单记录','我的订单','价格维护','利润分析','导出记录','存储与备份','开发者工具'])
    await expect(page.getByRole('button',{name,exact:true})).toHaveCount(0);
  await expect(page.locator('.finance-cost')).toHaveCount(0);
  const requests=await page.evaluate(()=>(window as any).__requests);
  expect(requests.some((r:any)=>['settings','backup_status','analytics','orders','outputs'].includes(r.action))).toBe(false);
  await page.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText(/SERVICE_|连接失败|请联系(?:管理员|维护人员)|证书/);
  expect(JSON.parse(await page.evaluate(()=>sessionStorage.getItem('777-desktop-draft-v1'))||'{}').lines).toHaveLength(1);
});

test('developer packaging remains available without a business session',async({page})=>{
  await setup(page,'development',null,false);
  await expect(page.getByRole('heading',{name:'应用封包',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'封包母版',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'账户菜单',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'封包母版',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>(window as any).__requests.some((r:any)=>r.action==='developer'&&r.request.op==='package'))).toBe(true);
  const calls=await page.evaluate(()=>(window as any).__requests.map((r:any)=>r.action));
  expect(calls).not.toContain('prices');expect(calls).not.toContain('settings');expect(calls).not.toContain('connect');
});

test('rejected package settings show the structured error and never start a job',async({page})=>{
  await setup(page,'development');
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.evaluate(()=>(window as any).__savePackageError='DESKTOP_REQUEST_INVALID');
  await page.getByRole('button',{name:'封包母版',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('操作请求格式不匹配');
  expect(await page.evaluate(()=>(window as any).__requests.some((r:any)=>r.action==='developer'&&r.request.op==='package'))).toBe(false);
  await expect(page.getByRole('button',{name:'封包母版',exact:true})).toBeEnabled();
});
