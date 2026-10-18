import type { Page } from '@playwright/test';
export async function setup(page:Page,delivery:string,permissions:string[]|null=null) {
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
          case 'import_connection':return{connection};
          case 'pick_directory':return{directory:'D:\\Selected'};
          default:throw{code:'SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED'};
        }
      }}});
  },{delivery,permissions});
  await page.goto('/');
}
