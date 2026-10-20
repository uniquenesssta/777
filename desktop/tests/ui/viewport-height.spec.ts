// Geometry and interaction of real React pages; this fixture does not verify Host auth.
import {test,expect,type Page} from '@playwright/test';
import {setup} from './fixtures/package-bridge';

async function fillsWorkspace(page:Page,selector:string) {
  await expect.poll(()=>page.locator(selector).evaluate(el=>{
    const card=el.getBoundingClientRect(),main=document.querySelector('.workspace')!;
    const rect=main.getBoundingClientRect(),style=getComputedStyle(main);
    return Math.abs(card.bottom-(rect.bottom-parseFloat(style.paddingBottom)))<3;
  })).toBe(true);
}
test('five reported pages grow when the same window becomes taller',async({page},info)=>{
  await setup(page,'development');
  for(const [label,selector] of [['报价工作台','.workbench-grid'],['利润分析','.profit-page'],['导出记录','.tasks-card'],['存储与备份','.settings'],['开发者工具','.developer-page']]){
    await page.setViewportSize({width:1590,height:900});
    await page.getByRole('button',{name:label,exact:true}).click();
    if(label==='开发者工具')await page.getByRole('button',{name:'封包授权',exact:true}).click();
    await fillsWorkspace(page,selector);
    const before=await page.locator(selector).evaluate(el=>el.getBoundingClientRect().height);
    await page.setViewportSize({width:1590,height:1200});
    await fillsWorkspace(page,selector);
    const after=await page.locator(selector).evaluate(el=>el.getBoundingClientRect().height);
    expect(after-before).toBeCloseTo(300,0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:info.outputPath(`${label}-tall.png`)});
  }
});
test('long lists use available height, keep export pagination outside scrolling and retain last-row access',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__jobCount=100);
  await page.getByRole('button',{name:'导出记录',exact:true}).click();
  for(const height of [1084,768]){
    await page.setViewportSize({width:1590,height});
    await fillsWorkspace(page,'.tasks-card');
    const list=page.locator('.tasks-card>.orders-table-scroll');
    expect(await list.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
    await expect(page.getByRole('button',{name:'下一页',exact:true})).toBeInViewport();
    await list.locator('tbody tr').last().scrollIntoViewIfNeeded();
    await expect(list.locator('tbody tr').last()).toBeInViewport();
  }
  await page.getByRole('button',{name:'报价工作台',exact:true}).click();
  for(let i=0;i<18;i++)await page.getByRole('button',{name:'添加商品',exact:false}).click();
  const list=page.locator('.line-scroll');
  expect(await list.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
  await list.locator('.quote-row').last().scrollIntoViewIfNeeded();
  await expect(list.locator('.quote-row').last()).toBeInViewport();
  await expect(page.getByRole('button',{name:'计算报价',exact:true})).toBeInViewport();
});
test('profit chart resizes in both directions without growing its container repeatedly',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>(window as any).__analysisOrders=1);
  await page.getByRole('button',{name:'利润分析',exact:true}).click();
  const svg=page.locator('.profit-chart-scroll>svg');
  await page.setViewportSize({width:1590,height:1200});
  await fillsWorkspace(page,'.profit-page');
  const tall=await svg.evaluate(el=>el.getBoundingClientRect().height);
  await page.setViewportSize({width:1590,height:900});
  await fillsWorkspace(page,'.profit-page');
  await expect.poll(()=>svg.evaluate(el=>el.getBoundingClientRect().height)).toBeLessThan(tall-200);
  await expect(page.getByText('查看汇总数据',{exact:true})).toBeInViewport();
});
test('short and narrow windows can scroll to the final business actions',async({page})=>{
  await setup(page,'development');
  for(const viewport of [{width:1366,height:600},{width:720,height:600},{width:390,height:600}]){
    await page.setViewportSize(viewport);
    for(const [label,action] of [['报价工作台','计算报价'],['存储与备份','生成今日备份'],['开发者工具','返回应用封包']]){
      await page.getByRole('button',{name:label,exact:true}).click();
      if(label==='开发者工具')await page.getByRole('button',{name:'封包授权',exact:true}).click();
      const button=page.getByRole('button',{name:action,exact:true});
      await button.scrollIntoViewIfNeeded();
      await expect(button).toBeInViewport();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    }
  }
});
