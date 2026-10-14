// Presentation-only native IPC stand-in; real service and financial gates remain separate.
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import { inspectPresentation } from "../native-presentation.mjs";
const pageErrors=new WeakMap<Page,string[]>();
test.beforeEach(({page})=>{const errors:string[]=[];pageErrors.set(page,errors);page.on("pageerror",e=>errors.push(e.message));});
test.afterEach(({page})=>{expect(pageErrors.get(page)).toEqual([]);});

async function bootstrap(page: Page, delivery="manager", failure=false) {
  await page.addInitScript(({delivery,failure})=>{
    let attempts=0;
    const callbacks=new Map();let next=1;
    Object.defineProperty(window,"__TAURI_INTERNALS__",{value:{
      metadata:{currentWindow:{label:"main"},currentWebview:{label:"main"}},
      transformCallback:(f:unknown)=>{callbacks.set(next,f);return next++;},unregisterCallback:(id:number)=>callbacks.delete(id),
      invoke:async(command:string,{request}: {request: {action:string}})=>{
        if(command!=="desktop_action")return 0;
        const role=delivery==="manager"?"admin":"sales";
        switch(request.action) {
          case "connection":return {delivery,automatic:true,connection:null,pending:false};
          case "bootstrap":
            if(failure && attempts++===0)throw {status:401,code:"DEVICE_NOT_AUTHORIZED"};
            return {delivery,automatic:true,session:{role,username:"中文测试账户".repeat(20),subject:"synthetic",pending:false}};
          case "prices":return {price_version_id:"presentation-v1",items:[{product_id:"单件",single:true,sale:"10",k:"1",...(role==="admin"?{cost:"4"}:{})}]};
          case "settings":return {revision:"1",export_dir:"\\\\localhost\\中文共享\\报价表",image_dir:"\\\\localhost\\中文共享\\报价图片"};
          case "backup_status":return {status:"ready",target:"synthetic",last_success:"—"};
          default:throw {status:400,code:"UNEXPECTED_PRESENTATION_REQUEST"};
        }
      }
    }});
    localStorage.setItem("777-desktop-draft-v1",JSON.stringify({schema:"777-desktop-draft-v1",details:{customer:"中文长客户名称".repeat(20),order_ref:"长订单号".repeat(20),wechat:"中文微信".repeat(20)},lines:Array.from({length:30},(_,i)=>({id:"row"+i,raw:{line_kind:"normal",product_id:"单件",q:"1",h:"",w:"",name:""}}))}));
  },{delivery,failure});
  await page.goto("/");
}

for(const delivery of ["manager","sales"]) {
  test(`${delivery} local fonts, original icons and compact layout at four emulated scales`,async({page},info)=>{
    await bootstrap(page,delivery);
    await expect(page.getByRole("button",{name:"添加商品",exact:false})).toBeEnabled();
    const output=info.outputPath("presentation");fs.mkdirSync(output,{recursive:true});
    const result=await inspectPresentation(page,output,delivery);
    expect(result.samples).toHaveLength(4);
    expect(result.samples.every(s=>s.table_scrollable)).toBeTruthy();
    for(const label of ["服务地址","服务证书（PEM）","账号","密码"])await expect(page.getByLabel(label,{exact:true})).toHaveCount(0);
    const region=page.getByRole("region",{name:"商品明细滚动区"});
    await region.focus();await region.press("End");
    await expect.poll(()=>region.evaluate(e=>e.scrollTop)).toBeGreaterThan(0);
    await page.getByRole("button",{name:"存储与备份",exact:true}).click();
    const path=page.getByLabel("报价图片保存位置");
    await expect(path).toHaveValue(/中文共享/);
    await expect(path).toHaveAttribute("title",/中文共享/);
    if(delivery==="sales")await expect(path).toHaveAttribute("readonly","");
  });
  test(`${delivery} failed automatic entry retries without technical/login controls`,async({page})=>{
    await bootstrap(page,delivery,true);
    await expect(page.getByRole("heading",{name:"暂时无法进入记账器"})).toBeVisible();
    for(const label of ["服务地址","服务证书（PEM）","账号","密码"])await expect(page.getByLabel(label,{exact:true})).toHaveCount(0);
    await page.getByRole("button",{name:"重新连接",exact:true}).click();
    await expect(page.getByRole("button",{name:"添加商品",exact:false})).toBeEnabled();
  });
}

test("keyboard dialog returns focus and missing resources have explicit fallback",async({page})=>{
  await page.route("**/fonts/*",route=>route.abort());
  await page.route("**/icons/a09ba.svg",route=>route.abort());
  await bootstrap(page);
  await expect(page.getByText("字体资源加载失败，当前使用系统字体。",{exact:true})).toBeVisible();
  await expect(page.getByRole("img",{name:"图标不可用"})).toBeVisible();
  const add=page.getByRole("button",{name:"添加商品",exact:false});
  await add.focus();await add.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(add).toBeFocused();
});
