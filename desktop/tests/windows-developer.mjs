// Real debug Tauri window → typed native IPC → private launcher → real NSIS build.
import { chromium, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { connectNativeBrowser } from './native-cdp.mjs';
const [port, output, delivery, version, destination, fixtureRoot] = process.argv.slice(2);
if (!fixtureRoot) throw Error("OWNED_DATA_FIXTURE_REQUIRED");
const browser = await connectNativeBrowser((endpoint, options) => chromium.connectOverCDP(endpoint, options), `http://127.0.0.1:${port}`);
let page;
try {
  const pageStarted = Date.now();
  while(Date.now()-pageStarted<60000){page=browser.contexts().flatMap(c=>c.pages()).find(p=>!p.isClosed()&&!p.url().startsWith('devtools:')&&p.url()!=='about:blank');if(page)break;await new Promise(r=>setTimeout(r,100));}
  fs.writeFileSync(output+'/developer-startup.json',JSON.stringify({elapsed_ms:Date.now()-pageStarted,ready:!!page,contexts:browser.contexts().length,pages:browser.contexts().flatMap(c=>c.pages()).map(p=>({url:p.url(),closed:p.isClosed()}))},null,2));
  if(!page)throw Error('DEVELOPER_PAGE_REQUIRED');
  await expect(page.getByRole('button', {name:'开发部署',exact:true})).toBeVisible({timeout:60000});
  await page.getByRole('button', {name:'开发部署',exact:true}).click();
  await expect(page.getByText('本机服务', {exact:true})).toBeVisible();
  await page.evaluate(async()=>document.fonts.ready);
  const capture = async name => page.screenshot({path:output+'/'+name+'.png'});
  await capture('developer-native-window');
  const metrics=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio}));
  fs.writeFileSync(output+'/native-metrics.json',JSON.stringify({native:metrics,comparison:'1440x884 and 720x900 are CDP viewport emulations, not physical monitor or OS DPI claims'},null,2));
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:884,deviceScaleFactor:1,mobile:false});
  await capture('developer-ready');
  await page.getByRole('button',{name:'新建空账本',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('当前账本与草稿保留');
  await capture('developer-create-dialog');
  await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
  const original = await page.getByLabel('存储位置',{exact:true}).inputValue();
  await page.getByLabel('存储位置',{exact:true}).fill(path.join(fixtureRoot,'新建账本'));
  await page.getByLabel('备份位置',{exact:true}).fill(path.join(fixtureRoot,'新建备份'));
  await page.getByRole('button',{name:'新建空账本',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'创建并读取',exact:true}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0,{timeout:60000});
  await expect(page.getByRole('region',{name:'开发部署'})).toHaveCount(0,{timeout:60000});
  await page.getByRole('button',{name:'价格维护',exact:true}).click();
  await expect(page.getByRole('button',{name:'＋ 添加商品',exact:true})).toBeEnabled({timeout:15000});
  await capture('developer-new-ledger-prices');
  await page.getByRole('button',{name:'开发部署',exact:true}).click();
  await page.getByLabel('存储位置',{exact:true}).fill(original);
  await page.getByRole('button',{name:'读取此位置',exact:true}).click();
  await expect(page.getByRole('region',{name:'开发部署'})).toHaveCount(0,{timeout:60000});
  await page.getByRole('button',{name:'开发部署',exact:true}).click();
  await expect(page.getByLabel('存储位置',{exact:true})).toHaveValue(original);
  const hidden=path.join(fixtureRoot,'隐藏每日副本');
  await page.getByLabel('隐藏位置',{exact:true}).fill(hidden);
  await page.getByRole('button',{name:'保存备份设置',exact:true}).click();
  await expect(page.getByRole('button',{name:'保存备份设置',exact:true})).toBeEnabled({timeout:60000});
  const devState=()=>page.evaluate(async()=>window.__TAURI_INTERNALS__.invoke('desktop_action',{request:{action:'developer',request:{op:'status'}}}));
  const savedHidden=(await devState()).daily.hidden_dir;
  expect(savedHidden).not.toBe('');
  expect(fs.realpathSync.native(savedHidden).toLowerCase()).toBe(fs.realpathSync.native(hidden).toLowerCase());
  await page.getByRole('button',{name:'生成今日备份',exact:true}).click();
  await expect(page.getByRole('button',{name:'生成今日备份',exact:true})).toBeEnabled({timeout:60000});
  const backed=await devState();
  expect(backed.daily_result.normal.ok).toBeTruthy();expect(backed.daily_result.hidden.ok).toBeTruthy();
  const restoreFile=path.join(backed.backup_dir,`${backed.ledger_id}-${backed.last_backup.business_date}-${backed.last_backup.backup_id}`,'data.qbackup');
  await page.getByRole('button',{name:'导入备份',exact:true}).click();
  await page.getByLabel('恢复文件',{exact:true}).fill(restoreFile);
  await page.getByLabel('新存储位置',{exact:true}).fill(path.join(fixtureRoot,'恢复读取账本'));
  await capture('developer-restore-dialog');
  await page.getByRole('button',{name:'导入并读取',exact:true}).click();
  await expect(page.getByRole('region',{name:'开发部署'})).toHaveCount(0,{timeout:60000});
  await page.getByRole('button',{name:'开发部署',exact:true}).click();
  expect((await devState()).ledger_id).toBe(backed.ledger_id);
  await capture('developer-restored');
  await page.getByLabel('存储位置',{exact:true}).fill(original);
  await page.getByRole('button',{name:'读取此位置',exact:true}).click();
  await expect(page.getByRole('region',{name:'开发部署'})).toHaveCount(0,{timeout:60000});
  await page.getByRole('button',{name:'开发部署',exact:true}).click();
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
  await cdp.send('Emulation.setDeviceMetricsOverride',{width:720,height:900,deviceScaleFactor:1,mobile:false});
  await page.evaluate(()=>window.scrollTo(0,0));
  const fields=await page.locator('.developer-path .compact-field').evaluateAll(nodes=>nodes.map(n=>{const label=n.querySelector('span').getBoundingClientRect(),input=n.querySelector('input').getBoundingClientRect();return Math.abs(label.top+label.height/2-input.top-input.height/2);}));
  expect(fields.every(offset=>offset<2)).toBeTruthy();
  const sizes=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
  expect(sizes.document).toBeLessThanOrEqual(sizes.viewport+1);
  await capture('developer-narrow');
  await cdp.send('Emulation.clearDeviceMetricsOverride');
  await cdp.detach();
} catch(error) {
  if(page) {
    await page.screenshot({path:output+'/developer-error.png'}).catch(()=>{});
    const diagnosis=await page.evaluate(async()=>({alerts:[...document.querySelectorAll('[role="alert"]')].map(n=>n.textContent),dialogs:[...document.querySelectorAll('[role="dialog"]')].map(n=>n.textContent),state:await window.__TAURI_INTERNALS__.invoke('desktop_action',{request:{action:'developer',request:{op:'status'}}}).catch(e=>({error:e}))})).catch(e=>({error:String(e)}));
    fs.writeFileSync(output+'/developer-error.json',JSON.stringify(diagnosis,null,2));
  }
  throw error;
} finally {await browser.close();}
