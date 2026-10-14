import fs from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, expect } from '@playwright/test';
import { connectNativeBrowser } from './native-cdp.mjs';
import { productionOrigin } from './native-origin.mjs';

// Submission leaves both deliveries on DetailPage, whose return button is
// disabled until useWorkbench finishes the original submission/refresh.
export async function recordAutomaticEntry(page, output, report, timeout = 15000) {
  await expect(page.locator('main.workspace')).toHaveAttribute('aria-busy', 'false', {timeout});
  await expect(page.getByRole('button', {name:'返回订单记录', exact:true})).toBeEnabled({timeout});
  await page.screenshot({path:output+'/native-autostart-'+report.delivery+'.png'});
  const completed={...report,status:'passed',UI_idle_before_native_close:true};
  fs.writeFileSync(output+'/native-autostart.json',JSON.stringify(completed,null,2));
  return completed;
}

async function main() {
const [port, output, delivery]=process.argv.slice(2);
let report={status:'running',delivery};
try {
const browser=await connectNativeBrowser((endpoint,options)=>chromium.connectOverCDP(endpoint,options),`http://127.0.0.1:${port}`, {report:v=>fs.writeFileSync(output+'/native-cdp-connection.json',JSON.stringify(v,null,2))});
try {
  let page;
  for(let n=0;n<100;n++) {
    page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().includes('tauri.localhost'));
    if(page)break;await new Promise(r=>setTimeout(r,100));
  }
  if(!page)throw Error('ACTUAL_TAURI_PAGE_NOT_FOUND');
  const origin=productionOrigin(page.url());
  await expect(page.getByRole('button',{name:'添加商品',exact:false})).toBeVisible({timeout:20000});
  for(const label of ['服务地址','服务证书（PEM）','证书 SHA-256 指纹','账号','密码'])await expect(page.getByLabel(label,{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'登录',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'添加商品',exact:false}).click();
  await page.getByLabel('商品',{exact:true}).selectOption('单件');
  await page.getByRole('button',{name:'添加',exact:true}).click();
  await page.getByLabel('订单号',{exact:true}).fill('device-native-'+delivery);
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await page.getByRole('button',{name:'核对并提交订单'}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'追加备注',exact:true})).toBeVisible();
  const result=await page.evaluate(async()=>{
    const invoke=request=>window.__TAURI_INTERNALS__.invoke('desktop_action',{request});
    const prices=await invoke({action:'prices'});
    let manualDenied=false;
    try{await invoke({action:'connect',connection:{url:'https://127.0.0.1:1',certificate_pem:'',certificate_sha256:''},username:'admin',password:'123456'});}catch(e){manualDenied=e.code==='MANUAL_LOGIN_DISABLED';}
    return {prices,manualDenied,storage:JSON.stringify(localStorage)};
  });
  if(!result.manualDenied)throw Error('FORMAL_MANUAL_LOGIN_REACHED');
  if(delivery==='sales' && JSON.stringify(result.prices).includes('cost'))throw Error('SALES_COST_LEAK');
  if(/device_secret|certificate_pem|ticket|token/.test(result.storage))throw Error('SECRET_IN_FRONTEND_STORAGE');
  report={...report,production_origin:origin,automatic_business_entry:true,no_configuration_or_login_controls:true,actual_IPC_HTTPS_submit:true,manual_login_direct_invoke_denied:true,sales_fields_restricted:delivery==='sales',secrets_not_in_frontend_storage:true};
  await recordAutomaticEntry(page,output,report);
} finally {await browser.close();}
} catch(error) {
  fs.writeFileSync(output+'/native-autostart.json',JSON.stringify({...report,status:'failed',failure:String(error)},null,2));
  throw error;
}
}

if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url))await main();
