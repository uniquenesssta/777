// Real debug Tauri window → typed native IPC → private launcher → real NSIS build.
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import { connectNativeBrowser } from './native-cdp.mjs';
const [port, output, delivery, version, destination] = process.argv.slice(2);
const browser = await connectNativeBrowser((endpoint, options) => chromium.connectOverCDP(endpoint, options), `http://127.0.0.1:${port}`);
try {
  let page;
  for(let i=0;i<100;i++){page=browser.contexts().flatMap(c=>c.pages()).find(p=>!p.url().startsWith('devtools:')&&p.url()!=='about:blank');if(page)break;await new Promise(r=>setTimeout(r,100));}
  if(!page)throw Error('DEVELOPER_PAGE_REQUIRED');
  await expect(page.getByRole('button', {name:'开发部署',exact:true})).toBeVisible({timeout:60000});
  await page.getByRole('button', {name:'开发部署',exact:true}).click();
  await expect(page.getByText('本机服务', {exact:true})).toBeVisible();
  await page.evaluate(async()=>document.fonts.ready);
  const capture = async name => page.screenshot({path:output+'/'+name+'.png'});
  await capture('developer-ready');
  await page.getByRole('button',{name:'新建空账本',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('当前账本与草稿保留');
  await capture('developer-create-dialog');
  await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
  await page.getByLabel('版本号',{exact:true}).fill(version);
  await page.getByLabel('输出位置',{exact:true}).fill(destination);
  await page.getByRole('button',{name:'联网安装',exact:true}).click();
  await page.getByRole('button',{name:delivery==='manager'?'一键封包母版':'一键封包子版',exact:true}).click();
  await expect(page.getByText('构建中',{exact:true})).toBeVisible({timeout:15000});
  await expect(page.locator('.developer-package-actions button')).toHaveCount(2);
  for(const button of await page.locator('.developer-package-actions button').all())await expect(button).toBeDisabled();
  await capture('developer-building');
  const deadline = Date.now()+40*60*1000;
  while (Date.now()<deadline) {
    if(await page.getByText('封包失败',{exact:true}).isVisible()) {
      await capture('developer-failed');
      throw Error(await page.locator('.developer-log').textContent());
    }
    if(await page.getByRole('button',{name:'打开产物目录',exact:true}).isVisible())break;
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await expect(page.getByRole('button',{name:'打开产物目录',exact:true})).toBeVisible();
  await capture('developer-succeeded');
  const state = await page.evaluate(async()=>window.__TAURI_INTERNALS__.invoke('desktop_action',{request:{action:'developer',request:{op:'status'}}}));
  if(state.job.state!=='succeeded'||state.job.delivery!==delivery)throw Error('DEVELOPER_JOB_MISMATCH');
  fs.writeFileSync(output+'/developer-job.json',JSON.stringify(state.job,null,2));
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:720,height:900,deviceScaleFactor:1,mobile:false});
  const sizes=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  expect(sizes.document).toBeLessThanOrEqual(sizes.viewport+1);
  await capture('developer-narrow');
  await cdp.send('Emulation.clearDeviceMetricsOverride');
  await cdp.detach();
} finally {await browser.close();}
