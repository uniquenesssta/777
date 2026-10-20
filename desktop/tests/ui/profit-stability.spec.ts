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
