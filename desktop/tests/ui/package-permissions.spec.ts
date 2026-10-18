// UI wiring only. No installer or remote host is invoked by this fixture.
import {test,expect,type Page} from '@playwright/test';
async function setup(page:Page,delivery:string,permissions:string[]|null=null) {
  await page.addInitScript(({delivery,permissions})=>{
    const connection={url:'https://192.168.4.38:8477',certificate_sha256:'a'.repeat(64),certificate_pem:'fixture'};
    const target={target:{connection,ledger_id:'fixture-ledger'},verified:true};
    const state={daily:{hidden_dir:'D:\\Hidden',daily_hour:23},root:'D:\\Dev',backup_dir:'D:\\Backup',ledger_id:'fixture-ledger',last_backup:null,connection,
      preferences:{output:'D:\\Packages',version:'0.1.0',runtime:'downloadBootstrapper'},job:null};
    (window as any).__requests=[];
    Object.defineProperty(window,'__TAURI_INTERNALS__',{value:{metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},transformCallback:()=>1,unregisterCallback:()=>{},
      invoke:async(command:string,{request:r}:{request:any})=>{
        if(command!=='desktop_action')return 0;
        (window as any).__requests.push(r);
        switch(r.action){
          case 'ui_diagnostic':return null;
          case 'connection':return{delivery,permissions,automatic:true,pending:false,connection:delivery==='development'?connection:null};
          case 'bootstrap':return{delivery,automatic:true,session:{role:delivery==='sales'?'sales':'admin',username:'fixture',subject:'fixture',pending:false}};
          case 'prices':return{price_version_id:'fixture',items:[{product_id:'商品',sale:'10',unit_sale:'10',k:'1',single:true}]};
          case 'settings':return{revision:'1',export_dir:'D:\\Excel',image_dir:'D:\\Images'};
          case 'developer':return state;
          case 'package_target':case 'use_current_package_target':return target;
          case 'pick_directory':return{directory:'D:\\Selected'};
          default:throw{code:'SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED'};
        }
      }}});
  },{delivery,permissions});
  await page.goto('/');
}
test('package choices send the reviewed policy and do not require typed paths or version',async({page},info)=>{
  await setup(page,'development');
  await page.getByRole('button',{name:'开发部署',exact:true}).click();
  const card=page.locator('.package-choices');
  await expect(card.locator('input[type=text]')).toHaveCount(0);
  await card.getByLabel('成本、利润与内部财务报表',{exact:true}).uncheck();
  await expect(card.getByLabel('价格维护（包含成本）',{exact:true})).not.toBeChecked();
  await card.getByRole('button',{name:'使用当前已连接的 Host',exact:true}).click();
  await card.getByRole('button',{name:'选择文件夹',exact:true}).click();
  await card.getByRole('button',{name:'按所选权限封包母版',exact:true}).click();
  await expect(page.getByRole('dialog')).not.toContainText('成本、利润与内部财务报表');
  await page.getByRole('button',{name:'开始封包',exact:true}).click();
  const requests=await page.evaluate(()=>(window as any).__requests);
  const build=requests.find((r:any)=>r.action==='developer'&&r.request.op==='package');
  expect(build.request.delivery).toBe('manager');
  expect(build.request.permissions).toEqual(['quote','orders','edit_orders','exports','settings','backup']);
  expect(requests.some((r:any)=>r.action==='developer'&&r.request.op==='save_package'&&r.request.output==='D:\\Selected')).toBe(true);
  await card.getByLabel('子版',{exact:true}).check();
  await expect(card.getByLabel('成本、利润与内部财务报表 · 仅母版',{exact:true})).toBeDisabled();
  await page.setViewportSize({width:720,height:1100});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath('package-choices-720.png'),fullPage:true});
});
for(const delivery of ['manager','sales'])test(`${delivery} quote-only policy has no hidden-feature navigation or account menu`,async({page})=>{
  await setup(page,delivery,['quote']);
  await expect(page.getByRole('button',{name:'报价工作台',exact:true})).toBeVisible();
  for(const name of ['账户菜单','退出登录','订单记录','我的订单','价格维护','利润分析','导出记录','存储与备份','开发部署'])
    await expect(page.getByRole('button',{name,exact:true})).toHaveCount(0);
  await expect(page.locator('.finance-cost')).toHaveCount(0);
  const requests=await page.evaluate(()=>(window as any).__requests);
  expect(requests.some((r:any)=>['settings','backup_status','analytics','orders','outputs'].includes(r.action))).toBe(false);
  await page.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText(/SERVICE_|连接失败|请联系管理员|证书/);
  expect(JSON.parse(await page.evaluate(()=>localStorage.getItem('777-desktop-draft-v1'))||'{}').lines).toHaveLength(1);
});
