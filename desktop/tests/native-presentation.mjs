import { expect } from '@playwright/test';
import fs from 'node:fs';

export async function inspectPresentation(page, output, delivery) {
  const initial=await page.evaluate(()=>({device_pixel_ratio:devicePixelRatio,width:innerWidth,height:innerHeight,screen:{width:screen.width,height:screen.height,available_width:screen.availWidth,available_height:screen.availHeight}}));
  const session=await page.context().newCDPSession(page);
  const samples=[];
  try {
    for(const scale of [1,1.25,1.5,2]) {
      await session.send('Emulation.setDeviceMetricsOverride',{width:Math.round(1440/scale),height:Math.round(1000/scale),deviceScaleFactor:scale,mobile:false});
      await page.evaluate(async()=>{window.scrollTo(0,0);await document.fonts.ready;});
      await expect(page.locator('body')).toHaveCSS('font-family', /Noto Sans SC/);
      const result=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
        document_width:document.documentElement.scrollWidth,
        fonts:{chinese:document.fonts.check('14px "Noto Sans SC"','中文报价'),number:document.fonts.check('14px Inter','1234567890')},
        icons:[...document.querySelectorAll('img.icon')].map(n=>({source:n.getAttribute('src'),natural:n.naturalWidth,width:n.getBoundingClientRect().width})),
        table_scrollable:[...document.querySelectorAll('.line-scroll')].some(n=>n.scrollHeight>n.clientHeight)}));
      expect(result.document_width).toBeLessThanOrEqual(result.width+1);
      expect(result.fonts).toEqual({chinese:true,number:true});
      expect(result.icons.length).toBeGreaterThan(0);
      expect(result.icons.every(i=>i.natural>0 && Math.abs(i.width-i.natural)<1)).toBeTruthy();
      const file=`presentation-${delivery}-${Math.round(scale*100)}.png`;
      // Playwright's fullPage helper can resize using its cached viewport and
      // undo externally supplied CDP metrics. Capture the current viewport directly.
      const capture=await session.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      fs.writeFileSync(output+'/'+file,Buffer.from(capture.data,'base64'));
      expect(await page.evaluate(()=>innerWidth)).toBe(result.width);
      samples.push({scale,emulation:true,...result,screenshot:file});
    }
  } finally {await session.send('Emulation.clearDeviceMetricsOverride');await session.detach();}
  await expect(page.getByRole('button',{name:'账户菜单',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'退出登录',exact:true})).toHaveCount(0);
  const report={status:'passed',delivery,initial,samples,formal_account_controls_absent:true,
    scope:'Actual rendered DOM/fonts/assets and CDP scale emulation. Four emulations are not four actual OS DPI settings or multiple physical monitors.'};
  fs.writeFileSync(output+'/presentation.json',JSON.stringify(report,null,2));
  return report;
}
