import {test,expect,type Page} from '@playwright/test';
import {nativeClient,nativeHost} from './fixtures/native-client';
// Real React/Host data with classic scrollbar width simulated for Linux Chromium.
// This layout regression does not claim Windows/WebView2 acceptance.
async function sample(page:Page){
  return page.locator('.profit-chart-scroll, .profit-pie').evaluate(async el=>{
    const frames:string[]=[];
    for(let i=0;i<50;i++){
      await new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()));
      const svg=el.querySelector('svg')!;
      frames.push(JSON.stringify([el.clientWidth,el.clientHeight,svg.getAttribute('width'),svg.getAttribute('height')]));
    }
    return [...new Set(frames.slice(20))];
  });
}
test.afterEach(async({request})=>{expect((await request.post(nativeHost+'/cleanup',{data:{}})).ok()).toBe(true);});
test('all four profit charts settle with classic scrollbars, resizing and fractional zoom',async({page,request},info)=>{
  await nativeClient(page,request);
  await page.addStyleTag({content:'::-webkit-scrollbar{width:15px;height:15px}::-webkit-scrollbar-thumb{background:#aaa}'});
  await page.getByRole('button',{name:'利润分析',exact:true}).click();
  await page.getByRole('button',{name:'近1天',exact:true}).click();
  for(const zoom of [1,1.25]){
    await page.evaluate(zoom=>document.documentElement.style.zoom=String(zoom),zoom);
    await page.setViewportSize({width:1366,height:901});
    for(const chart of ['柱状图','折线图','饼图','K线图']){
      await page.getByRole('button',{name:chart,exact:true}).click();
      await expect(page.locator('.profit-chart-scroll>svg, .profit-pie>svg')).toBeVisible();
      const frames=await sample(page);
      await info.attach(`${chart}-${zoom}-frames`,{body:JSON.stringify(frames),contentType:'application/json'});
      expect(frames,`${chart}, zoom ${zoom} keeps changing without new data`).toHaveLength(1);
    }
  }
});

test('switching chart types preserves the summary card positions',async({page,request},info)=>{
  await nativeClient(page,request);
  await page.addStyleTag({content:'::-webkit-scrollbar{width:15px;height:15px}::-webkit-scrollbar-thumb{background:#aaa}'});
  await page.getByRole('button',{name:'利润分析',exact:true}).click();
  for(const viewport of [{width:1440,height:884},{width:1100,height:768},{width:720,height:600}]){
    await page.setViewportSize(viewport);
    await page.evaluate(()=>{document.querySelector('.workspace')!.scrollTop=0;});
    const values=[], stages=[];
    for(const chart of ['柱状图','折线图','饼图','K线图','柱状图']){
      // Programmatic click avoids Playwright scrolling a short window to the controls.
      await page.getByRole('button',{name:chart,exact:true}).evaluate((el:HTMLElement)=>el.click());
      await sample(page);
      stages.push(await page.locator('.profit-visualization').evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};}));
      values.push(await page.locator('.analysis-metrics article').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};})));
    }
    await info.attach(`summary-${viewport.width}`,{body:JSON.stringify(values),contentType:'application/json'});
    for(const value of values.slice(1))expect(value).toEqual(values[0]);
    for(const stage of stages.slice(1))expect(stage).toEqual(stages[0]);
    await page.screenshot({path:info.outputPath(`profit-fixed-${viewport.width}.png`)});
  }
});
